from pathlib import Path

import yaml

from app.models import DeviceMapping


DEFAULT_CONFIG_PATH = Path("config/devices.yaml")


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
