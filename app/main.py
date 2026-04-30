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
from app.arbitration import decide_wake
from app.config import load_announcement_config, load_devices
from app.models import (
    ActiveContextSetRequest,
    AnnouncementFramesResponse,
    AnnouncementJobCreated,
    AnnouncementJobRequest,
    DevicesResponse,
    SessionEndRequest,
    WakeDetectedRequest,
)
from app.session_store import SessionStore

app = FastAPI(title="Xiaozhi Gateway")
logger = logging.getLogger(__name__)
session_store = SessionStore()
announcement_jobs = AudioJobStore()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/devices", response_model=DevicesResponse)
def devices() -> DevicesResponse:
    return DevicesResponse(devices=load_devices())


@app.get("/active-context")
def get_active_context() -> dict:
    context = session_store.get()
    if context is None:
        return {"active": False}
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
    decision = decide_wake(load_devices(), session_store, request)
    if decision["type"] == "unknown_device":
        raise HTTPException(status_code=404, detail="device not found")
    return decision


@app.post("/session/end")
def end_session(request: SessionEndRequest) -> dict[str, bool]:
    context = session_store.get()
    if context is None:
        return {"ended": False}

    if context.device_id != request.device_id:
        raise HTTPException(
            status_code=409,
            detail="active session belongs to another device",
        )

    session_store.clear()
    return {"ended": True}


@app.post("/announcement/jobs", response_model=AnnouncementJobCreated)
def create_announcement_job(request: AnnouncementJobRequest) -> AnnouncementJobCreated:
    device = next(
        (device for device in load_devices() if device.device_id == request.device_id),
        None,
    )
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")

    announcement_config = load_announcement_config()
    try:
        frames = synthesize_announcement_frames(
            request.text,
            announcement_config,
        )
    except AnnouncementDisabledError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UnsupportedAnnouncementProviderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MissingTtsApiKeyError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except TtsAuthenticationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except TtsTimeoutError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except TtsEmptyAudioError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except TtsProviderError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    logger.info(
        "announcement job synthesized provider=%s voice=%s frames=%d",
        announcement_config.provider,
        announcement_config.doubao.voice,
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
