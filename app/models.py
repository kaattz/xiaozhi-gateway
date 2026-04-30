from typing import Any, Literal

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
    device_id: str
    client_id: str = ""
    text: str = Field(min_length=1, max_length=300)
    mode: Literal["announcement", "question"] = "announcement"


class AnnouncementJobCreated(AudioJobCreated):
    listen_after_playback: bool = False
    listen_timeout_seconds: int = 0


class AnnouncementFramesResponse(AudioFramesResponse):
    pass


class PendingConfirmationCreateRequest(BaseModel):
    device_id: str
    client_id: str = ""
    room_id: str
    prompt: str = Field(min_length=1, max_length=300)
    ttl_seconds: int = Field(default=30, ge=5, le=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PendingConfirmationCreated(BaseModel):
    confirmation_id: str
    device_id: str
    client_id: str = ""
    room_id: str
    prompt: str
    status: str
    expires_at: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class PendingConfirmationResolveRequest(BaseModel):
    decision: Literal["yes", "no"]
    device_id: str
    room_id: str
    source: str = ""


class PendingConfirmationResolved(BaseModel):
    confirmation_id: str
    status: str
    decision: Literal["yes", "no"]
    device_id: str
    room_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
