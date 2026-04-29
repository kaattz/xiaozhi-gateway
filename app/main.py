import base64

from fastapi import FastAPI, HTTPException, Query

from app.arbitration import decide_wake
from app.config import load_devices, load_remote_text_config
from app.models import (
    ActiveContextSetRequest,
    DevicesResponse,
    RemoteTextFramesResponse,
    RemoteTextJobCreated,
    RemoteTextJobRequest,
    SessionEndRequest,
    WakeDetectedRequest,
)
from app.remote_text_audio import (
    FRAME_DURATION_MS,
    SAMPLE_RATE,
    encode_raw_opus_frames,
    normalize_wav_to_pcm_s16le,
    synthesize_remote_text_wav,
)
from app.remote_text_jobs import RemoteTextJobStore
from app.session_store import SessionStore

app = FastAPI(title="Xiaozhi Gateway")
session_store = SessionStore()
remote_text_jobs = RemoteTextJobStore()


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


@app.post("/remote-text/jobs", response_model=RemoteTextJobCreated)
def create_remote_text_job(request: RemoteTextJobRequest) -> RemoteTextJobCreated:
    device = next(
        (device for device in load_devices() if device.device_id == request.device_id),
        None,
    )
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")

    remote_text_config = load_remote_text_config()
    wav = synthesize_remote_text_wav(request.text, remote_text_config)
    pcm = normalize_wav_to_pcm_s16le(wav, remote_text_config.ffmpeg_binary)
    frames = encode_raw_opus_frames(pcm)
    if not frames:
        raise HTTPException(status_code=500, detail="opus encoding produced no frames")

    job = remote_text_jobs.create(
        device_id=device.device_id,
        frames=frames,
        sample_rate=SAMPLE_RATE,
        frame_duration_ms=FRAME_DURATION_MS,
    )
    return RemoteTextJobCreated(
        job_id=job.job_id,
        device_id=job.device_id,
        sample_rate=job.sample_rate,
        frame_duration_ms=job.frame_duration_ms,
        frame_count=len(job.frames),
        expires_at=job.expires_at,
    )


@app.get("/remote-text/jobs/{job_id}/frames", response_model=RemoteTextFramesResponse)
def get_remote_text_frames(
    job_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(4, ge=1, le=16),
) -> RemoteTextFramesResponse:
    job = remote_text_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    total_frames = len(job.frames)
    page_frames = job.frames[offset : offset + limit]
    next_offset = offset + len(page_frames)
    if next_offset >= total_frames:
        next_offset = None
    return RemoteTextFramesResponse(
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
