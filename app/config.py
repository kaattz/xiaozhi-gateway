import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
import yaml

from app.models import DeviceMapping


DEFAULT_CONFIG_PATH = Path(os.getenv("XIAOZHI_GATEWAY_CONFIG", "config/devices.yaml"))
DEFAULT_DOUBAO_SPEECH_SPEED = "正常"
DOUBAO_SPEECH_RATE_BY_SPEED = {
    "慢速": -20,
    "正常": 0,
    "快速": 20,
}


class AnnouncementDoubaoConfig(BaseModel):
    app_id: str = Field(
        default_factory=lambda: os.getenv("XIAOZHI_DOUBAO_APP_ID", "")
    )
    access_key: str = Field(
        default_factory=lambda: os.getenv("XIAOZHI_DOUBAO_ACCESS_KEY", "")
    )
    resource_id: str = Field(
        default_factory=lambda: os.getenv(
            "XIAOZHI_DOUBAO_RESOURCE_ID",
            "seed-tts-2.0",
        )
    )
    voice: str = Field(
        default_factory=lambda: os.getenv(
            "XIAOZHI_DOUBAO_VOICE",
            "zh_female_xiaohe_uranus_bigtts",
        )
    )
    sample_rate: int = Field(
        default_factory=lambda: int(os.getenv("XIAOZHI_DOUBAO_SAMPLE_RATE", "16000"))
    )
    speech_speed: str = Field(
        default_factory=lambda: os.getenv(
            "XIAOZHI_DOUBAO_SPEECH_SPEED",
            DEFAULT_DOUBAO_SPEECH_SPEED,
        )
    )

    @field_validator("speech_speed")
    @classmethod
    def validate_speech_speed(cls, value: str) -> str:
        value = str(value).strip()
        if value not in DOUBAO_SPEECH_RATE_BY_SPEED:
            choices = ", ".join(DOUBAO_SPEECH_RATE_BY_SPEED)
            raise ValueError(f"doubao speech_speed must be one of: {choices}")
        return value

    @property
    def speech_rate(self) -> int:
        return DOUBAO_SPEECH_RATE_BY_SPEED[self.speech_speed]


class AnnouncementConfig(BaseModel):
    enabled: bool = Field(
        default_factory=lambda: parse_bool(
            os.getenv("XIAOZHI_ANNOUNCEMENT_ENABLED", "true")
        )
    )
    provider: str = Field(
        default_factory=lambda: os.getenv("XIAOZHI_ANNOUNCEMENT_PROVIDER", "doubao")
    )
    frame_format: str = "opus"
    frame_duration_ms: int = 60
    doubao: AnnouncementDoubaoConfig = Field(default_factory=AnnouncementDoubaoConfig)


class PlaybackConfig(BaseModel):
    ha_base_url: str = Field(
        default_factory=lambda: os.getenv("XIAOZHI_HA_BASE_URL", "")
    )
    ha_access_token: str = Field(
        default_factory=lambda: os.getenv("XIAOZHI_HA_ACCESS_TOKEN", "")
    )
    public_stream_base_url: str = Field(
        default_factory=lambda: os.getenv("XIAOZHI_PLAYBACK_PUBLIC_STREAM_BASE_URL", "")
    )
    request_timeout_seconds: float = Field(default=5.0, gt=0)

    @field_validator("ha_base_url", "public_stream_base_url")
    @classmethod
    def trim_url(cls, value: str) -> str:
        return str(value).strip().rstrip("/")


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def apply_announcement_env_overrides(values: dict) -> dict:
    merged = dict(values)
    doubao = dict(merged.get("doubao") or {})

    env_fields = {
        "XIAOZHI_ANNOUNCEMENT_ENABLED": ("enabled", parse_bool),
        "XIAOZHI_ANNOUNCEMENT_PROVIDER": ("provider", str),
    }
    for env_name, (field_name, cast) in env_fields.items():
        if env_name in os.environ:
            merged[field_name] = cast(os.environ[env_name])

    doubao_env_fields = {
        "XIAOZHI_DOUBAO_APP_ID": ("app_id", str),
        "XIAOZHI_DOUBAO_ACCESS_KEY": ("access_key", str),
        "XIAOZHI_DOUBAO_RESOURCE_ID": ("resource_id", str),
        "XIAOZHI_DOUBAO_VOICE": ("voice", str),
        "XIAOZHI_DOUBAO_SAMPLE_RATE": ("sample_rate", int),
        "XIAOZHI_DOUBAO_SPEECH_SPEED": ("speech_speed", str),
    }
    for env_name, (field_name, cast) in doubao_env_fields.items():
        if env_name in os.environ:
            doubao[field_name] = cast(os.environ[env_name])

    if doubao:
        merged["doubao"] = doubao
    return merged


def apply_playback_env_overrides(values: dict) -> dict:
    merged = dict(values)
    env_fields = {
        "XIAOZHI_HA_BASE_URL": ("ha_base_url", str),
        "XIAOZHI_HA_ACCESS_TOKEN": ("ha_access_token", str),
        "XIAOZHI_PLAYBACK_PUBLIC_STREAM_BASE_URL": ("public_stream_base_url", str),
        "XIAOZHI_PLAYBACK_REQUEST_TIMEOUT_SECONDS": ("request_timeout_seconds", float),
    }
    for env_name, (field_name, cast) in env_fields.items():
        if env_name in os.environ:
            merged[field_name] = cast(os.environ[env_name])
    return merged


def load_devices(config_path: Path = DEFAULT_CONFIG_PATH) -> list[DeviceMapping]:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    raw_devices = raw.get("devices") or {}

    devices: list[DeviceMapping] = []
    device_ids: set[str] = set()
    client_ids: set[str] = set()

    for key, values in raw_devices.items():
        if not values.get("room_id"):
            raise ValueError(f"missing room_id for device: {key}")

        device = DeviceMapping(key=key, **values)
        if not device.wake_group:
            device.wake_group = key
        if device.device_id in device_ids:
            raise ValueError(f"duplicate device_id: {device.device_id}")
        device_ids.add(device.device_id)

        if device.client_id:
            if device.client_id in client_ids:
                raise ValueError(f"duplicate client_id: {device.client_id}")
            client_ids.add(device.client_id)

        devices.append(device)

    return devices


def load_announcement_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> AnnouncementConfig:
    if not config_path.exists():
        return AnnouncementConfig()

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    announcement = apply_announcement_env_overrides(raw.get("announcement") or {})
    return AnnouncementConfig.model_validate(announcement)


def load_playback_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> PlaybackConfig:
    if not config_path.exists():
        return PlaybackConfig()

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    playback = apply_playback_env_overrides(raw.get("playback") or {})
    return PlaybackConfig.model_validate(playback)
