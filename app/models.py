import math

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeviceMapping(BaseModel):
    key: str
    device_id: str
    client_id: str = ""
    room_id: str
    room_name: str
    ha_area_id: str
    ha_device_id: str = ""
    wake_group: str = ""
    priority: int = 0
    mic_gain_offset_db: float = 0.0


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
    wake_rms_dbfs: float
    timestamp: float | None = None

    @field_validator("wake_rms_dbfs")
    @classmethod
    def validate_wake_rms_dbfs(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("invalid wake_rms_dbfs")
        return value


class SessionEndRequest(BaseModel):
    device_id: str


class AudioJobCreated(BaseModel):
    job_id: str
    device_id: str
    sample_rate: int
    frame_duration_ms: int
    frame_count: int
    expires_at: float


class AudioFramesResponse(BaseModel):
    job_id: str
    sample_rate: int
    frame_duration_ms: int
    frames_base64: list[str]
    offset: int = 0
    next_offset: int | None = None
    total_frames: int = 0


class AnnouncementJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_id: str
    client_id: str = ""
    text: str = Field(min_length=1, max_length=300)


class AnnouncementJobCreated(AudioJobCreated):
    pass


class AnnouncementFramesResponse(AudioFramesResponse):
    pass
