import yaml

from app.addon_options import render_devices_config


def test_render_devices_config_from_addon_options():
    output = render_devices_config(
        {
            "announcement_enabled": True,
            "announcement_provider": "doubao",
            "doubao_app_id": "app-id",
            "doubao_access_key": "access-key",
            "doubao_resource_id": "seed-tts-2.0",
            "doubao_voice": "zh_female_xiaohe_jupiter_bigtts",
            "doubao_sample_rate": 16000,
            "devices": [
                {
                    "key": "living_room_xiaozhi",
                    "device_id": "a0:b1:c2:d3:e4:f5",
                    "client_id": "livingroom_xiaozhi",
                    "room_id": "living_room",
                    "room_name": "客厅",
                    "ha_area_id": "living_room",
                    "ha_device_id": "",
                    "wake_group": "public_area",
                    "priority": 10,
                    "mic_gain_offset_db": -2.5,
                }
            ],
        }
    )

    config = yaml.safe_load(output)

    assert config["devices"]["living_room_xiaozhi"] == {
        "device_id": "a0:b1:c2:d3:e4:f5",
        "client_id": "livingroom_xiaozhi",
        "room_id": "living_room",
        "room_name": "客厅",
        "ha_area_id": "living_room",
        "ha_device_id": "",
        "wake_group": "public_area",
        "priority": 10,
        "mic_gain_offset_db": -2.5,
    }
    assert "remote_text" not in config
    assert config["announcement"] == {
        "enabled": True,
        "provider": "doubao",
        "frame_format": "opus",
        "frame_duration_ms": 60,
        "doubao": {
            "app_id": "app-id",
            "access_key": "access-key",
            "resource_id": "seed-tts-2.0",
            "voice": "zh_female_xiaohe_jupiter_bigtts",
            "sample_rate": 16000,
        },
    }


def test_render_devices_config_rejects_missing_device_id():
    try:
        render_devices_config(
            {
                "devices": [
                    {
                        "key": "living_room_xiaozhi",
                        "device_id": "",
                        "room_id": "living_room",
                        "room_name": "客厅",
                        "ha_area_id": "living_room",
                    }
                ]
            }
        )
    except ValueError as error:
        assert "missing device_id for device: living_room_xiaozhi" in str(error)
    else:
        raise AssertionError("expected missing device_id to fail")
