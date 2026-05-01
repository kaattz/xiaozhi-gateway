import os
from pathlib import Path

from pydantic import BaseModel, Field
import yaml

from app.models import DeviceMapping


DEFAULT_CONFIG_PATH = Path(os.getenv("XIAOZHI_GATEWAY_CONFIG", "config/devices.yaml"))


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
    }
    for env_name, (field_name, cast) in doubao_env_fields.items():
        if env_name in os.environ:
            doubao[field_name] = cast(os.environ[env_name])

    if doubao:
        merged["doubao"] = doubao
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
