import base64
import asyncio
import json
import logging
import uuid
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.audio_frames import FRAME_DURATION_MS, SAMPLE_RATE
from app.audio_jobs import AudioJobStore
from app.announcement_audio import (
    AnnouncementDisabledError,
    MissingTtsApiKeyError,
    TtsAuthenticationError,
    TtsEmptyAudioError,
    TtsProviderError,
    TtsTimeoutError,
    UnsupportedAnnouncementProviderError,
    synthesize_announcement_frames,
)
from app.arbitration import WakeArbitrationStore, decide_wake
from app.config import load_announcement_config, load_devices, load_playback_config
from app.models import (
    ActiveContextSetRequest,
    AnnouncementFramesResponse,
    AnnouncementJobCreated,
    AnnouncementJobRequest,
    DevicesResponse,
    PlaybackSessionCreated,
    PlaybackSessionRequest,
    SessionEndRequest,
    WakeDetectedRequest,
)
from app.playback import (
    PlaybackSessionStore,
    call_home_assistant_play_media,
    validate_public_stream_base_url,
)
from app.session_store import MULTIPLE_ACTIVE_CONTEXTS, SessionStore

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Xiaozhi Gateway")
logger = logging.getLogger(__name__)
session_store = SessionStore()
wake_arbitration_store = WakeArbitrationStore()
announcement_jobs = AudioJobStore()
playback_sessions = PlaybackSessionStore()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/devices", response_model=DevicesResponse)
def devices() -> DevicesResponse:
    return DevicesResponse(devices=load_devices())


@app.get("/active-context")
def get_active_context(device_id: str | None = None) -> dict:
    context = session_store.get(device_id)
    if context is None:
        logger.info("get_active_context device_id=%s result=no_active_context", device_id)
        return {"active": False}
    if context == MULTIPLE_ACTIVE_CONTEXTS:
        logger.info("get_active_context device_id=%s result=multiple_active_contexts", device_id)
        return {"active": False, "status": MULTIPLE_ACTIVE_CONTEXTS}
    logger.info(
        "get_active_context device_id=%s result=active room_id=%s ha_area_id=%s",
        device_id,
        context.room_id,
        context.ha_area_id,
    )
    return {"active": True, **context.model_dump()}


@app.post("/active-context")
def set_active_context(request: ActiveContextSetRequest) -> dict:
    for device in load_devices():
        if device.device_id == request.device_id:
            context = session_store.set(device)
            return {"active": True, **context.model_dump()}
    raise HTTPException(status_code=404, detail="device not found")


@app.delete("/active-context")
def clear_active_context() -> dict[str, bool]:
    session_store.clear()
    return {"active": False}


@app.post("/wake-detected")
def wake_detected(request: WakeDetectedRequest) -> dict:
    decision = decide_wake(
        load_devices(),
        session_store,
        request,
        arbitration_store=wake_arbitration_store,
    )
    if decision["type"] == "unknown_device":
        raise HTTPException(status_code=404, detail="device not found")
    return decision


@app.post("/session/end")
def end_session(request: SessionEndRequest) -> dict[str, bool]:
    context = session_store.get(request.device_id)
    if context is None:
        return {"ended": False}

    session_store.clear(request.device_id)
    return {"ended": True}


def _find_device(device_id: str):
    return next((device for device in load_devices() if device.device_id == device_id), None)


def _announcement_status() -> dict:
    config = load_announcement_config()
    return {
        "enabled": config.enabled,
        "provider": config.provider,
        "tts_configured": bool(
            config.doubao.app_id.strip() and config.doubao.access_key.strip()
        ),
        "voice": config.doubao.voice,
        "sample_rate": config.doubao.sample_rate,
        "speech_speed": config.doubao.speech_speed,
        "speech_rate": config.doubao.speech_rate,
        "resource_id": config.doubao.resource_id,
    }


def _log_announcement_tts_failure(
    *,
    request: AnnouncementJobRequest,
    reason: str,
    error: Exception,
) -> None:
    status = _announcement_status()
    logger.error(
        "announcement tts unavailable reason=%s provider=%s configured=%s "
        "voice=%s sample_rate=%s resource_id=%s device_id=%s client_id=%s "
        "detail=%s",
        reason,
        status["provider"],
        status["tts_configured"],
        status["voice"],
        status["sample_rate"],
        status["resource_id"],
        request.device_id,
        request.client_id,
        str(error),
    )


@app.get("/announcement/status")
def announcement_status() -> dict:
    return _announcement_status()


@app.post("/announcement/jobs", response_model=AnnouncementJobCreated)
def create_announcement_job(request: AnnouncementJobRequest) -> AnnouncementJobCreated:
    device = _find_device(request.device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")

    announcement_config = load_announcement_config()
    logger.info(
        "announcement job requested provider=%s configured=%s voice=%s "
        "sample_rate=%s resource_id=%s device_id=%s client_id=%s text_length=%d",
        announcement_config.provider,
        bool(
            announcement_config.doubao.app_id.strip()
            and announcement_config.doubao.access_key.strip()
        ),
        announcement_config.doubao.voice,
        announcement_config.doubao.sample_rate,
        announcement_config.doubao.resource_id,
        device.device_id,
        request.client_id,
        len(request.text),
    )
    try:
        frames = synthesize_announcement_frames(
            request.text,
            announcement_config,
        )
    except AnnouncementDisabledError as exc:
        _log_announcement_tts_failure(
            request=request,
            reason="disabled",
            error=exc,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnsupportedAnnouncementProviderError as exc:
        _log_announcement_tts_failure(
            request=request,
            reason="unsupported_provider",
            error=exc,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MissingTtsApiKeyError as exc:
        _log_announcement_tts_failure(
            request=request,
            reason="missing_credentials",
            error=exc,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except TtsAuthenticationError as exc:
        _log_announcement_tts_failure(
            request=request,
            reason="authentication_failed",
            error=exc,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except TtsTimeoutError as exc:
        _log_announcement_tts_failure(
            request=request,
            reason="timeout",
            error=exc,
        )
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except TtsEmptyAudioError as exc:
        _log_announcement_tts_failure(
            request=request,
            reason="empty_audio",
            error=exc,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except TtsProviderError as exc:
        _log_announcement_tts_failure(
            request=request,
            reason="provider_error",
            error=exc,
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logger.info(
        "announcement job synthesized provider=%s voice=%s device_id=%s frames=%d",
        announcement_config.provider,
        announcement_config.doubao.voice,
        device.device_id,
        len(frames),
    )
    job = announcement_jobs.create(
        device_id=device.device_id,
        frames=frames,
        sample_rate=SAMPLE_RATE,
        frame_duration_ms=FRAME_DURATION_MS,
    )
    return AnnouncementJobCreated(
        job_id=job.job_id,
        device_id=job.device_id,
        sample_rate=job.sample_rate,
        frame_duration_ms=job.frame_duration_ms,
        frame_count=len(job.frames),
        expires_at=job.expires_at,
    )


@app.get("/announcement/jobs/{job_id}/frames", response_model=AnnouncementFramesResponse)
def get_announcement_frames(
    job_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(4, ge=1, le=16),
) -> AnnouncementFramesResponse:
    job = announcement_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    total_frames = len(job.frames)
    page_frames = job.frames[offset : offset + limit]
    next_offset = offset + len(page_frames)
    if next_offset >= total_frames:
        next_offset = None
    return AnnouncementFramesResponse(
        job_id=job.job_id,
        sample_rate=job.sample_rate,
        frame_duration_ms=job.frame_duration_ms,
        frames_base64=[
            base64.b64encode(frame).decode("ascii")
            for frame in page_frames
        ],
        offset=offset,
        next_offset=next_offset,
        total_frames=total_frames,
    )


@app.post("/playback/sessions", response_model=PlaybackSessionCreated)
def create_playback_session(
    request: PlaybackSessionRequest,
    http_request: Request,
) -> PlaybackSessionCreated:
    device = _find_device(request.device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")

    playback_config = load_playback_config()
    try:
        public_base = validate_public_stream_base_url(playback_config.public_stream_base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    session_id = uuid.uuid4().hex
    stream_path = f"/playback/sessions/{session_id}/stream.ogg"
    stream_url = public_base + stream_path
    upload_url = str(http_request.url_for("upload_playback_session", session_id=session_id))
    parsed_upload = urlsplit(upload_url)
    if parsed_upload.scheme == "http":
        upload_url = "ws://" + parsed_upload.netloc + parsed_upload.path
    elif parsed_upload.scheme == "https":
        upload_url = "wss://" + parsed_upload.netloc + parsed_upload.path

    session = playback_sessions.create(
        request,
        session_id=session_id,
        stream_url=stream_url,
        upload_url=upload_url,
    )
    logger.info(
        "playback session created session=%s device_id=%s client_id=%s entity_id=%s stream_host=%s",
        session.session_id,
        session.device_id,
        session.client_id,
        session.media_player_entity_id,
        urlsplit(session.stream_url).netloc,
    )
    return PlaybackSessionCreated(
        session_id=session.session_id,
        device_id=session.device_id,
        client_id=session.client_id,
        upload_url=session.upload_url,
        stream_url=session.stream_url,
    )


async def _call_play_media_once(session, playback_config) -> None:
    if session.ha_play_media_called:
        return
    if session.buffered_audio_ms <= 0:
        session.fail("no_audio")
        return

    try:
        await asyncio.to_thread(
            call_home_assistant_play_media,
            playback_config,
            session.media_player_entity_id,
            session.stream_url,
        )
        session.mark_ha_play_media_called()
        logger.info(
            "playback HA play_media called session=%s entity_id=%s stream_url=%s",
            session.session_id,
            session.media_player_entity_id,
            session.stream_url,
        )
    except Exception as exc:
        logger.error(
            "playback HA play_media failed session=%s detail=%s",
            session.session_id,
            exc,
        )
        session.fail("ha_play_media_failed")


@app.websocket("/playback/sessions/{session_id}/upload")
async def upload_playback_session(websocket: WebSocket, session_id: str) -> None:
    session = playback_sessions.get(session_id)
    if session is None:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    playback_config = load_playback_config()
    try:
        while True:
            while status := session.pop_status():
                await websocket.send_json(status)
            if session.terminal:
                break

            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=0.05)
            except asyncio.TimeoutError:
                continue

            if message["type"] == "websocket.disconnect":
                break

            data = message.get("bytes")
            if data is not None:
                ready_for_ha = session.add_frame(data)
                if ready_for_ha:
                    await _call_play_media_once(session, playback_config)
                continue

            text = message.get("text")
            if text:
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    session.fail("invalid_control_message")
                    continue
                command = payload.get("type")
                if command == "end":
                    await _call_play_media_once(session, playback_config)
                    session.close_input()
                elif command == "cancel":
                    session.cancel("cancelled")
                else:
                    session.fail("invalid_control_message")
    except WebSocketDisconnect:
        return


@app.get("/playback/sessions/{session_id}/stream.ogg")
def stream_playback_session(session_id: str) -> StreamingResponse:
    session = playback_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    if session.cancelled:
        raise HTTPException(status_code=410, detail=session.fail_reason or "session cancelled")
    if session.failed:
        raise HTTPException(status_code=500, detail=session.fail_reason or "session failed")

    return StreamingResponse(
        session.iter_ogg(),
        media_type="audio/ogg; codecs=opus",
    )


@app.delete("/playback/sessions/{session_id}")
def cancel_playback_session(session_id: str) -> dict[str, bool]:
    session = playback_sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    session.cancel("cancelled")
    return {"cancelled": True}
