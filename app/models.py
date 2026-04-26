from pydantic import BaseModel


class DeviceMapping(BaseModel):
    key: str
    device_id: str
    client_id: str = ""
    room_id: str
    room_name: str
    ha_area_id: str
    ha_device_id: str = ""


class DevicesResponse(BaseModel):
    devices: list[DeviceMapping]


class ActiveContextSetRequest(BaseModel):
    device_id: str


class ActiveContext(BaseModel):
    device_id: str
    client_id: str = ""
    room_id: str
    room_name: str
    ha_area_id: str
    ha_device_id: str = ""
    expires_at: float


class WakeDetectedRequest(BaseModel):
    device_id: str
    client_id: str = ""
    wake_word: str
    timestamp: float | None = None


class SessionEndRequest(BaseModel):
    device_id: str
