from pydantic import BaseModel, Field


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


class RemoteTextJobRequest(BaseModel):
    device_id: str
    client_id: str = ""
    text: str = Field(min_length=1, max_length=120)


class RemoteTextJobCreated(BaseModel):
    job_id: str
    device_id: str
    sample_rate: int
    frame_duration_ms: int
    frame_count: int
    expires_at: float


class RemoteTextFramesResponse(BaseModel):
    job_id: str
    sample_rate: int
    frame_duration_ms: int
    frames_base64: list[str]
