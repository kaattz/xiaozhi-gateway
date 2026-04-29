from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_haos_addon_metadata_exposes_gateway_port_and_piper_options():
    config = read("config.yaml")

    assert "slug: xiaozhi_gateway" in config
    assert "8125/tcp: 8125" in config
    assert "piper_host: core-piper" in config
    assert "piper_port: 10200" in config
    assert "addon_config" in config


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
    assert "ffmpeg libopus0" in dockerfile
    assert "COPY run.sh /run.sh" in dockerfile
    assert 'CMD ["/run.sh"]' in dockerfile


def test_run_script_uses_addon_options_and_addon_config_file():
    run_sh = read("run.sh")

    assert "/data/options.json" in run_sh
    assert "XIAOZHI_REMOTE_TEXT_PROVIDER=wyoming" in run_sh
    assert "XIAOZHI_GATEWAY_CONFIG=/config/devices.yaml" in run_sh
    assert "uvicorn app.main:app" in run_sh
