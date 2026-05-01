from fastapi.testclient import TestClient
import pytest

from app.config import load_announcement_config, load_devices
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
                "wake_group": "living_room_xiaozhi",
                "priority": 0,
                "mic_gain_offset_db": 0.0,
            },
            {
                "key": "bedroom_xiaozhi",
                "device_id": "11:22:33:44:55:66",
                "client_id": "",
                "room_id": "bedroom",
                "room_name": "卧室",
                "ha_area_id": "bedroom",
                "ha_device_id": "",
                "wake_group": "bedroom_xiaozhi",
                "priority": 0,
                "mic_gain_offset_db": 0.0,
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


def test_announcement_config_uses_defaults_when_missing(tmp_path):
    config = tmp_path / "devices.yaml"
    config.write_text("devices: {}\n", encoding="utf-8")

    announcement = load_announcement_config(config)

    assert announcement.enabled is True
    assert announcement.provider == "doubao"
    assert announcement.frame_format == "opus"
    assert announcement.frame_duration_ms == 60
    assert announcement.doubao.app_id == ""
    assert announcement.doubao.access_key == ""
    assert announcement.doubao.resource_id == "seed-tts-2.0"
    assert announcement.doubao.voice == "zh_female_xiaohe_uranus_bigtts"
    assert announcement.doubao.sample_rate == 16000
    assert announcement.doubao.speech_speed == "正常"
    assert announcement.doubao.speech_rate == 0


def test_announcement_config_loads_yaml_values(tmp_path):
    config = tmp_path / "devices.yaml"
    config.write_text(
        """
devices: {}
announcement:
  enabled: true
  provider: "doubao"
  frame_format: "opus"
  frame_duration_ms: 60
  doubao:
    app_id: "app-id"
    access_key: "access-key"
    resource_id: "seed-tts-2.0"
    voice: "voice-id"
    sample_rate: 16000
    speech_speed: "慢速"
""",
        encoding="utf-8",
    )

    announcement = load_announcement_config(config)

    assert announcement.enabled is True
    assert announcement.provider == "doubao"
    assert announcement.doubao.app_id == "app-id"
    assert announcement.doubao.access_key == "access-key"
    assert announcement.doubao.resource_id == "seed-tts-2.0"
    assert announcement.doubao.voice == "voice-id"
    assert announcement.doubao.speech_speed == "慢速"
    assert announcement.doubao.speech_rate == -20


def test_announcement_config_env_overrides_yaml_for_secret(monkeypatch, tmp_path):
    config = tmp_path / "devices.yaml"
    config.write_text(
        """
devices: {}
announcement:
  enabled: false
  provider: "bailian"
  doubao:
    app_id: "old-app"
    access_key: "old-key"
    resource_id: "old-resource"
    voice: "old-voice"
    sample_rate: 24000
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("XIAOZHI_ANNOUNCEMENT_ENABLED", "true")
    monkeypatch.setenv("XIAOZHI_ANNOUNCEMENT_PROVIDER", "doubao")
    monkeypatch.setenv("XIAOZHI_DOUBAO_APP_ID", "new-app")
    monkeypatch.setenv("XIAOZHI_DOUBAO_ACCESS_KEY", "new-key")
    monkeypatch.setenv("XIAOZHI_DOUBAO_RESOURCE_ID", "seed-tts-2.0")
    monkeypatch.setenv("XIAOZHI_DOUBAO_VOICE", "new-voice")
    monkeypatch.setenv("XIAOZHI_DOUBAO_SAMPLE_RATE", "16000")
    monkeypatch.setenv("XIAOZHI_DOUBAO_SPEECH_SPEED", "快速")

    announcement = load_announcement_config(config)

    assert announcement.enabled is True
    assert announcement.provider == "doubao"
    assert announcement.doubao.app_id == "new-app"
    assert announcement.doubao.access_key == "new-key"
    assert announcement.doubao.resource_id == "seed-tts-2.0"
    assert announcement.doubao.voice == "new-voice"
    assert announcement.doubao.sample_rate == 16000
    assert announcement.doubao.speech_speed == "快速"
    assert announcement.doubao.speech_rate == 20
