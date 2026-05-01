from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_haos_addon_metadata_exposes_gateway_port_and_announcement_options():
    config = yaml.safe_load(read("config.yaml"))

    assert config["version"] == "0.1.15"
    assert config["slug"] == "xiaozhi_gateway"
    assert config["ports"]["8125/tcp"] == 8125
    assert config["options"]["addon_version"] == "0.1.15"
    assert config["schema"]["addon_version"] == "str"
    assert "piper_host" not in config["options"]
    assert "piper_port" not in config["options"]
    assert config["options"]["announcement_enabled"] is True
    assert config["options"]["announcement_provider"] == "doubao"
    assert config["options"]["doubao_app_id"] == ""
    assert config["options"]["doubao_access_key"] == ""
    assert config["options"]["doubao_resource_id"] == "seed-tts-2.0"
    assert config["options"]["doubao_voice"]
    assert config["options"]["doubao_sample_rate"] == 16000
    assert config["options"]["doubao_speech_speed"] == "正常"
    assert config["schema"]["announcement_enabled"] == "bool"
    assert config["schema"]["announcement_provider"] == "str"
    assert config["schema"]["doubao_app_id"] == "str"
    assert config["schema"]["doubao_access_key"] == "password?"
    assert config["schema"]["doubao_resource_id"] == "str"
    assert config["schema"]["doubao_speech_speed"] == "list(正常|慢速|快速)"
    assert config["options"]["devices"][0]["key"] == "living_room_xiaozhi"
    assert config["schema"]["devices"][0]["device_id"] == "str"
    assert config["map"][0]["type"] == "addon_config"


def test_repository_metadata_allows_home_assistant_to_add_github_repo():
    repository = yaml.safe_load(read("repository.yaml"))

    assert repository["name"] == "Xiaozhi Gateway Add-ons"
    assert "xiaozhi-gateway" in repository["url"]
    assert repository["maintainer"]


def test_dockerfile_installs_audio_dependencies_and_runs_addon_script():
    dockerfile = read("Dockerfile")

    assert "ARG BUILD_FROM=python:3.12-slim" in dockerfile
    assert "io.hass.type" in dockerfile
    assert "io.hass.arch" in dockerfile
    assert "libopus0" in dockerfile
    assert "ffmpeg" not in dockerfile
    assert "COPY run.sh /run.sh" in dockerfile
    assert 'CMD ["/run.sh"]' in dockerfile


def test_run_script_uses_addon_options_and_addon_config_file():
    run_sh = read("run.sh")

    assert "/data/options.json" in run_sh
    assert "python -m app.addon_options" in run_sh
    assert "XIAOZHI_REMOTE_TEXT_PROVIDER" not in run_sh
    assert "XIAOZHI_WYOMING_HOST" not in run_sh
    assert "XIAOZHI_GATEWAY_CONFIG=/config/devices.yaml" in run_sh
    assert "uvicorn app.main:app" in run_sh
