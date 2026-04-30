from fastapi.testclient import TestClient

import app.main as main
from app.announcement_audio import (
    AnnouncementDisabledError,
    TtsAuthenticationError,
    TtsTimeoutError,
    UnsupportedAnnouncementProviderError,
)
from app.main import app

client = TestClient(app)


def test_announcement_creates_and_fetches_frames(monkeypatch):
    monkeypatch.setattr(
        main,
        "synthesize_announcement_frames",
        lambda text, config: [b"one", b"two", b"three", b"four", b"five"],
    )

    created = client.post(
        "/announcement/jobs",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "client_id": "xiaozhi-living-room",
            "text": "现在房间温度较高，是否打开空调。",
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["device_id"] == "aa:bb:cc:dd:ee:ff"
    assert body["sample_rate"] == 16000
    assert body["frame_duration_ms"] == 60
    assert body["frame_count"] == 5

    first = client.get(f"/announcement/jobs/{body['job_id']}/frames?offset=0&limit=4")
    assert first.status_code == 200
    assert first.json()["frames_base64"] == ["b25l", "dHdv", "dGhyZWU=", "Zm91cg=="]
    assert first.json()["offset"] == 0
    assert first.json()["next_offset"] == 4
    assert first.json()["total_frames"] == 5

    last = client.get(f"/announcement/jobs/{body['job_id']}/frames?offset=4&limit=4")
    assert last.status_code == 200
    assert last.json()["frames_base64"] == ["Zml2ZQ=="]
    assert last.json()["next_offset"] is None


def test_announcement_rejects_unknown_device():
    response = client.post(
        "/announcement/jobs",
        json={"device_id": "missing", "text": "hello"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "device not found"


def test_announcement_maps_disabled_and_unsupported_provider(monkeypatch):
    monkeypatch.setattr(
        main,
        "synthesize_announcement_frames",
        lambda text, config: (_ for _ in ()).throw(AnnouncementDisabledError("announcement disabled")),
    )
    disabled = client.post(
        "/announcement/jobs",
        json={"device_id": "aa:bb:cc:dd:ee:ff", "text": "hello"},
    )
    assert disabled.status_code == 400
    assert disabled.json()["detail"] == "announcement disabled"

    monkeypatch.setattr(
        main,
        "synthesize_announcement_frames",
        lambda text, config: (_ for _ in ()).throw(
            UnsupportedAnnouncementProviderError("unsupported announcement provider: bailian")
        ),
    )
    unsupported = client.post(
        "/announcement/jobs",
        json={"device_id": "aa:bb:cc:dd:ee:ff", "text": "hello"},
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["detail"] == "unsupported announcement provider: bailian"


def test_announcement_maps_auth_and_timeout_errors(monkeypatch):
    monkeypatch.setattr(
        main,
        "synthesize_announcement_frames",
        lambda text, config: (_ for _ in ()).throw(TtsAuthenticationError("doubao authentication failed")),
    )
    auth = client.post(
        "/announcement/jobs",
        json={"device_id": "aa:bb:cc:dd:ee:ff", "text": "hello"},
    )
    assert auth.status_code == 502
    assert auth.json()["detail"] == "doubao authentication failed"

    monkeypatch.setattr(
        main,
        "synthesize_announcement_frames",
        lambda text, config: (_ for _ in ()).throw(TtsTimeoutError("doubao synthesis timeout")),
    )
    timeout = client.post(
        "/announcement/jobs",
        json={"device_id": "aa:bb:cc:dd:ee:ff", "text": "hello"},
    )
    assert timeout.status_code == 504
    assert timeout.json()["detail"] == "doubao synthesis timeout"
