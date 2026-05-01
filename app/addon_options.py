import json
import sys
from pathlib import Path
from typing import Any

import yaml


REQUIRED_DEVICE_FIELDS = ("key", "device_id", "room_id", "room_name", "ha_area_id")


def render_devices_config(options: dict[str, Any]) -> str:
    devices = options.get("devices") or []
    rendered_devices: dict[str, dict[str, str]] = {}

    for device in devices:
        key = str(device.get("key") or "").strip()
        if not key:
            raise ValueError("missing key for device")

        for field in REQUIRED_DEVICE_FIELDS:
            value = str(device.get(field) or "").strip()
            if not value:
                raise ValueError(f"missing {field} for device: {key}")

        rendered_devices[key] = {
            "device_id": str(device["device_id"]).strip().lower(),
            "client_id": str(device.get("client_id") or "").strip(),
            "room_id": str(device["room_id"]).strip(),
            "room_name": str(device["room_name"]).strip(),
            "ha_area_id": str(device["ha_area_id"]).strip(),
            "ha_device_id": str(device.get("ha_device_id") or "").strip(),
        }

    config = {
        "devices": rendered_devices,
        "announcement": {
            "enabled": bool(options.get("announcement_enabled", True)),
            "provider": str(options.get("announcement_provider") or "doubao").strip(),
            "frame_format": "opus",
            "frame_duration_ms": 60,
            "doubao": {
                "app_id": str(options.get("doubao_app_id") or "").strip(),
                "access_key": str(options.get("doubao_access_key") or "").strip(),
                "resource_id": str(
                    options.get("doubao_resource_id") or "seed-tts-2.0"
                ).strip(),
                "voice": str(
                    options.get("doubao_voice")
                    or "zh_female_xiaohe_uranus_bigtts"
                ).strip(),
                "sample_rate": int(options.get("doubao_sample_rate") or 16000),
            },
        },
    }
    return yaml.safe_dump(config, allow_unicode=True, sort_keys=False)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: python -m app.addon_options OPTIONS_JSON OUTPUT_YAML")

    options_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    options = json.loads(options_path.read_text(encoding="utf-8"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_devices_config(options), encoding="utf-8")


if __name__ == "__main__":
    main()
