import base64
import logging

from fastapi import FastAPI, HTTPException, Query

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
from app.config import load_announcement_config, load_devices
from app.models import (
    ActiveContextSetRequest,
    AnnouncementFramesResponse,
    AnnouncementJobCreated,
    AnnouncementJobRequest,
    DevicesResponse,
    PendingConfirmationCreateRequest,
    PendingConfirmationCreated,
    PendingConfirmationResolveRequest,
    PendingConfirmationResolved,
    SessionEndRequest,
    WakeDetectedRequest,
)
from app.pending_confirmations import (
    PendingConfirmation,
    PendingConfirmationStore,
    PendingConflictError,
    PendingMismatchError,
    PendingNotFoundError,
    PendingResolvedError,
)
from app.session_store import MULTIPLE_ACTIVE_CONTEXTS, SessionStore

app = FastAPI(title="Xiaozhi Gateway")
logger = logging.getLogger(__name__)
session_store = SessionStore()
wake_arbitration_store = WakeArbitrationStore()
announcement_jobs = AudioJobStore()
pending_confirmations = PendingConfirmationStore()


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
        return {"active": False}
    if context == MULTIPLE_ACTIVE_CONTEXTS:
        return {"active": False, "status": MULTIPLE_ACTIVE_CONTEXTS}
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
        "mode=%s detail=%s",
        reason,
        status["provider"],
        status["tts_configured"],
        status["voice"],
        status["sample_rate"],
        status["resource_id"],
        request.device_id,
        request.client_id,
        request.mode,
        str(error),
    )


def _pending_created_response(item: PendingConfirmation) -> PendingConfirmationCreated:
    return PendingConfirmationCreated(
        confirmation_id=item.confirmation_id,
        device_id=item.device_id,
        client_id=item.client_id,
        room_id=item.room_id,
        prompt=item.prompt,
        status=item.status,
        expires_at=item.expires_at,
        metadata=item.metadata,
    )


@app.post("/pending-confirmations", response_model=PendingConfirmationCreated)
def create_pending_confirmation(
    request: PendingConfirmationCreateRequest,
) -> PendingConfirmationCreated:
    device = _find_device(request.device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    if request.room_id != device.room_id:
        raise HTTPException(status_code=409, detail="room_mismatch")

    try:
        item = pending_confirmations.create(
            device_id=device.device_id,
            client_id=request.client_id or device.client_id,
            room_id=request.room_id,
            prompt=request.prompt,
            ttl_seconds=request.ttl_seconds,
            metadata=request.metadata,
        )
    except PendingConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return _pending_created_response(item)


@app.get("/pending-confirmations/active")
def get_active_pending_confirmation(
    device_id: str | None = None,
    room_id: str | None = None,
) -> dict:
    item = pending_confirmations.get_active(device_id=device_id, room_id=room_id)
    if item is None:
        latest = pending_confirmations.get_latest(device_id=device_id, room_id=room_id)
        if latest is not None and latest.status == "expired":
            return {
                "active": False,
                "status": "expired",
                "confirmation_id": latest.confirmation_id,
            }
        return {"active": False, "status": "no_pending_confirmation"}
    return {
        "active": True,
        "confirmation_id": item.confirmation_id,
        "device_id": item.device_id,
        "client_id": item.client_id,
        "room_id": item.room_id,
        "prompt": item.prompt,
        "expires_at": item.expires_at,
        "metadata": item.metadata,
    }


@app.post(
    "/pending-confirmations/{confirmation_id}/resolve",
    response_model=PendingConfirmationResolved,
)
def resolve_pending_confirmation(
    confirmation_id: str,
    request: PendingConfirmationResolveRequest,
) -> PendingConfirmationResolved:
    try:
        item = pending_confirmations.resolve(
            confirmation_id,
            decision=request.decision,
            device_id=request.device_id,
            room_id=request.room_id,
        )
    except PendingNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (PendingMismatchError, PendingResolvedError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return PendingConfirmationResolved(
        confirmation_id=item.confirmation_id,
        status=item.status,
        decision=item.decision or request.decision,
        device_id=item.device_id,
        room_id=item.room_id,
        metadata=item.metadata,
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
        "sample_rate=%s resource_id=%s mode=%s device_id=%s client_id=%s text_length=%d",
        announcement_config.provider,
        bool(
            announcement_config.doubao.app_id.strip()
            and announcement_config.doubao.access_key.strip()
        ),
        announcement_config.doubao.voice,
        announcement_config.doubao.sample_rate,
        announcement_config.doubao.resource_id,
        request.mode,
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
        "announcement job synthesized provider=%s voice=%s mode=%s device_id=%s frames=%d",
        announcement_config.provider,
        announcement_config.doubao.voice,
        request.mode,
        device.device_id,
        len(frames),
    )
    job = announcement_jobs.create(
        device_id=device.device_id,
        frames=frames,
        sample_rate=SAMPLE_RATE,
        frame_duration_ms=FRAME_DURATION_MS,
    )
    listen_after_playback = request.mode == "question"
    if listen_after_playback:
        session_store.set(device)
    return AnnouncementJobCreated(
        job_id=job.job_id,
        device_id=job.device_id,
        sample_rate=job.sample_rate,
        frame_duration_ms=job.frame_duration_ms,
        frame_count=len(job.frames),
        expires_at=job.expires_at,
        listen_after_playback=listen_after_playback,
        listen_timeout_seconds=8 if listen_after_playback else 0,
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
