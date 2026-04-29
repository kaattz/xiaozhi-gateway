import os
from pathlib import Path

from pydantic import BaseModel, Field
import yaml

from app.models import DeviceMapping


DEFAULT_CONFIG_PATH = Path(os.getenv("XIAOZHI_GATEWAY_CONFIG", "config/devices.yaml"))


class RemoteTextConfig(BaseModel):
    provider: str = Field(
        default_factory=lambda: os.getenv("XIAOZHI_REMOTE_TEXT_PROVIDER", "wyoming")
    )
    wyoming_host: str = Field(
        default_factory=lambda: os.getenv("XIAOZHI_WYOMING_HOST", "core-piper")
    )
    wyoming_port: int = Field(
        default_factory=lambda: int(os.getenv("XIAOZHI_WYOMING_PORT", "10200"))
    )
    ffmpeg_binary: str = Field(
        default_factory=lambda: os.getenv("XIAOZHI_FFMPEG_BINARY", "ffmpeg")
    )


def apply_remote_text_env_overrides(values: dict) -> dict:
    merged = dict(values)
    env_fields = {
        "XIAOZHI_REMOTE_TEXT_PROVIDER": ("provider", str),
        "XIAOZHI_WYOMING_HOST": ("wyoming_host", str),
        "XIAOZHI_WYOMING_PORT": ("wyoming_port", int),
        "XIAOZHI_FFMPEG_BINARY": ("ffmpeg_binary", str),
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
        if device.device_id in device_ids:
            raise ValueError(f"duplicate device_id: {device.device_id}")
        device_ids.add(device.device_id)

        if device.client_id:
            if device.client_id in client_ids:
                raise ValueError(f"duplicate client_id: {device.client_id}")
            client_ids.add(device.client_id)

        devices.append(device)

    return devices


def load_remote_text_config(
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> RemoteTextConfig:
    if not config_path.exists():
        return RemoteTextConfig()

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    remote_text = apply_remote_text_env_overrides(raw.get("remote_text") or {})
    return RemoteTextConfig.model_validate(remote_text)
