from fastapi.testclient import TestClient

import app.main as main
from app.main import app

client = TestClient(app)


def test_remote_text_creates_and_fetches_frames(monkeypatch):
    client.delete("/active-context")

    monkeypatch.setattr(main, "synthesize_remote_text_wav", lambda text, config: b"wav")
    monkeypatch.setattr(
        main, "normalize_wav_to_pcm_s16le", lambda wav, ffmpeg_binary: b"pcm"
    )
    monkeypatch.setattr(main, "encode_raw_opus_frames", lambda pcm: [b"one", b"two"])

    created = client.post(
        "/remote-text/jobs",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "client_id": "xiaozhi-living-room",
            "text": "现在房间温度比较高",
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["sample_rate"] == 16000
    assert body["frame_duration_ms"] == 60
    assert body["frame_count"] == 2

    frames = client.get(f"/remote-text/jobs/{body['job_id']}/frames")
    assert frames.status_code == 200
    assert frames.json()["frames_base64"] == ["b25l", "dHdv"]
    assert frames.json()["offset"] == 0
    assert frames.json()["next_offset"] is None
    assert frames.json()["total_frames"] == 2


def test_remote_text_fetches_frames_by_page(monkeypatch):
    monkeypatch.setattr(main, "synthesize_remote_text_wav", lambda text, config: b"wav")
    monkeypatch.setattr(
        main, "normalize_wav_to_pcm_s16le", lambda wav, ffmpeg_binary: b"pcm"
    )
    monkeypatch.setattr(
        main,
        "encode_raw_opus_frames",
        lambda pcm: [b"one", b"two", b"three", b"four", b"five"],
    )

    created = client.post(
        "/remote-text/jobs",
        json={"device_id": "aa:bb:cc:dd:ee:ff", "text": "现在房间温度比较高"},
    )
    assert created.status_code == 200

    first = client.get(f"/remote-text/jobs/{created.json()['job_id']}/frames?offset=1&limit=2")
    assert first.status_code == 200
    assert first.json()["frames_base64"] == ["dHdv", "dGhyZWU="]
    assert first.json()["offset"] == 1
    assert first.json()["next_offset"] == 3
    assert first.json()["total_frames"] == 5

    last = client.get(f"/remote-text/jobs/{created.json()['job_id']}/frames?offset=3&limit=2")
    assert last.status_code == 200
    assert last.json()["frames_base64"] == ["Zm91cg==", "Zml2ZQ=="]
    assert last.json()["offset"] == 3
    assert last.json()["next_offset"] is None
    assert last.json()["total_frames"] == 5


def test_remote_text_rejects_unknown_device():
    response = client.post(
        "/remote-text/jobs",
        json={"device_id": "missing", "text": "hello"},
    )

    assert response.status_code == 404
