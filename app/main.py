from fastapi import FastAPI, HTTPException

from app.arbitration import decide_wake
from app.config import load_devices
from app.models import (
    ActiveContextSetRequest,
    DevicesResponse,
    SessionEndRequest,
    WakeDetectedRequest,
)
from app.session_store import SessionStore

app = FastAPI(title="Xiaozhi Gateway")
session_store = SessionStore()


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
