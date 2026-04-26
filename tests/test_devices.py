from fastapi.testclient import TestClient
import pytest

from app.config import load_devices
from app.main import app


def test_devices_returns_configured_device_mappings():
    client = TestClient(app)

    response = client.get("/devices")

    assert response.status_code == 200
    assert response.json() == {
        "devices": [
            {
                "key": "living_room_xiaozhi",
                "device_id": "aa:bb:cc:dd:ee:ff",
                "client_id": "",
                "room_id": "living_room",
                "room_name": "客厅",
                "ha_area_id": "living_room",
                "ha_device_id": "",
            },
            {
                "key": "bedroom_xiaozhi",
                "device_id": "11:22:33:44:55:66",
                "client_id": "",
                "room_id": "bedroom",
                "room_name": "卧室",
                "ha_area_id": "bedroom",
                "ha_device_id": "",
            },
        ]
    }


def test_device_registry_rejects_duplicate_device_id(tmp_path):
    config = tmp_path / "devices.yaml"
    config.write_text(
        """
devices:
  one:
    device_id: "same"
    room_id: "living_room"
    room_name: "Living Room"
    ha_area_id: "living_room"
  two:
    device_id: "same"
    room_id: "bedroom"
    room_name: "Bedroom"
    ha_area_id: "bedroom"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate device_id: same"):
        load_devices(config)


def test_device_registry_rejects_duplicate_non_empty_client_id(tmp_path):
    config = tmp_path / "devices.yaml"
    config.write_text(
        """
devices:
  one:
    device_id: "one"
    client_id: "same-client"
    room_id: "living_room"
    room_name: "Living Room"
    ha_area_id: "living_room"
  two:
    device_id: "two"
    client_id: "same-client"
    room_id: "bedroom"
    room_name: "Bedroom"
    ha_area_id: "bedroom"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate client_id: same-client"):
        load_devices(config)


def test_device_registry_rejects_missing_room_id(tmp_path):
    config = tmp_path / "devices.yaml"
    config.write_text(
        """
devices:
  one:
    device_id: "one"
    room_name: "Living Room"
    ha_area_id: "living_room"
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing room_id for device: one"):
        load_devices(config)
