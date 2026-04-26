from app.models import ActiveContext, DeviceMapping, WakeDetectedRequest
from app.session_store import SessionStore


def find_wake_device(
    devices: list[DeviceMapping], request: WakeDetectedRequest
) -> DeviceMapping | None:
    for device in devices:
        if device.device_id == request.device_id:
            return device

    return None


def decide_wake(
    devices: list[DeviceMapping],
    session_store: SessionStore,
    request: WakeDetectedRequest,
) -> dict:
    device = find_wake_device(devices, request)
    if device is None:
        return {"type": "unknown_device"}

    active = session_store.get()
    if active is not None and active.device_id != device.device_id:
        return {
            "type": "deny_session",
            "reason": "another_session_active",
            "active_device_id": active.device_id,
        }

    context = session_store.set(device)
    return _allow_response(context)


def _allow_response(context: ActiveContext) -> dict:
    return {
        "type": "allow_session",
        **context.model_dump(),
    }
