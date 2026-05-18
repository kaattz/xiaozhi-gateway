from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

import app.main as main
from app.main import app
from app.models import PlaybackSessionRequest
from app.playback import OggOpusMuxer, PlaybackSession, PlaybackSessionStore

ROOT = Path(__file__).resolve().parents[1]


def _configure_playback(monkeypatch):
    monkeypatch.setenv("XIAOZHI_HA_BASE_URL", "http://ha.local")
    monkeypatch.setenv("XIAOZHI_HA_ACCESS_TOKEN", "token")
    monkeypatch.setenv("XIAOZHI_PLAYBACK_PUBLIC_STREAM_BASE_URL", "http://gateway.local")


def test_playback_session_streams_uploaded_opus_as_ogg_and_calls_ha(monkeypatch):
    _configure_playback(monkeypatch)
    ha_calls = []
    monkeypatch.setattr(
        main,
        "call_home_assistant_play_media",
        lambda config, entity_id, stream_url: ha_calls.append((entity_id, stream_url)),
    )
    client = TestClient(app)

    created = client.post(
        "/playback/sessions",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "client_id": "voice-pe",
            "media_player_entity_id": "media_player.beosound2",
            "stream_format": "ogg_opus",
            "sample_rate": 24000,
            "frame_duration_ms": 60,
            "initial_buffer_ms": 300,
            "timeout_ms": 30000,
            "replace_existing": True,
        },
    )

    assert created.status_code == 200
    body = created.json()
    assert body["stream_url"].startswith("http://gateway.local/playback/sessions/")
    assert body["stream_url"].endswith("/stream.ogg")
    assert body["upload_url"].startswith("ws://")

    upload_path = urlsplit(body["upload_url"]).path
    with client.websocket_connect(upload_path) as websocket:
        for _ in range(5):
            websocket.send_bytes(b"\xf8\xff\xfe")
        websocket.send_json({"type": "end"})

    stream_path = urlsplit(body["stream_url"]).path
    streamed = client.get(stream_path)

    assert streamed.status_code == 200
    assert streamed.headers["content-type"].startswith("audio/ogg")
    assert streamed.content.startswith(b"OggS")
    assert b"OpusHead" in streamed.content
    assert b"OpusTags" in streamed.content
    assert b"\xf8\xff\xfe" in streamed.content
    assert ha_calls == [("media_player.beosound2", body["stream_url"])]


def test_playback_ha_service_call_runs_off_event_loop():
    source = (ROOT / "app/main.py").read_text(encoding="utf-8")

    assert "async def _call_play_media_once" in source
    assert "await asyncio.to_thread(" in source


def test_playback_session_calls_ha_when_short_reply_ends_before_initial_buffer(monkeypatch):
    _configure_playback(monkeypatch)
    ha_calls = []
    monkeypatch.setattr(
        main,
        "call_home_assistant_play_media",
        lambda config, entity_id, stream_url: ha_calls.append((entity_id, stream_url)),
    )
    client = TestClient(app)

    created = client.post(
        "/playback/sessions",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "client_id": "voice-pe",
            "media_player_entity_id": "media_player.beosound2",
            "sample_rate": 24000,
            "frame_duration_ms": 60,
            "initial_buffer_ms": 300,
            "timeout_ms": 30000,
        },
    )

    assert created.status_code == 200
    body = created.json()
    upload_path = urlsplit(body["upload_url"]).path
    with client.websocket_connect(upload_path) as websocket:
        websocket.send_bytes(b"\xf8\xff\xfe")
        websocket.send_json({"type": "end"})

    assert ha_calls == [("media_player.beosound2", body["stream_url"])]


def test_playback_session_rejects_unreachable_public_stream_base(monkeypatch):
    monkeypatch.setenv("XIAOZHI_HA_BASE_URL", "http://ha.local")
    monkeypatch.setenv("XIAOZHI_HA_ACCESS_TOKEN", "token")
    monkeypatch.setenv("XIAOZHI_PLAYBACK_PUBLIC_STREAM_BASE_URL", "http://127.0.0.1:8125")
    client = TestClient(app)

    response = client.post(
        "/playback/sessions",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "media_player_entity_id": "media_player.beosound2",
            "sample_rate": 24000,
            "frame_duration_ms": 60,
        },
    )

    assert response.status_code == 400
    assert "public stream base URL" in response.json()["detail"]


def test_playback_session_supersedes_existing_session(monkeypatch):
    _configure_playback(monkeypatch)
    monkeypatch.setattr(main, "call_home_assistant_play_media", lambda *args: None)
    client = TestClient(app)

    first = client.post(
        "/playback/sessions",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "client_id": "voice-pe",
            "media_player_entity_id": "media_player.beosound2",
            "sample_rate": 24000,
            "frame_duration_ms": 60,
        },
    ).json()
    second = client.post(
        "/playback/sessions",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "client_id": "voice-pe",
            "media_player_entity_id": "media_player.sonos",
            "sample_rate": 24000,
            "frame_duration_ms": 60,
        },
    ).json()

    assert first["session_id"] != second["session_id"]
    old_stream = client.get(urlsplit(first["stream_url"]).path)
    assert old_stream.status_code == 410


def test_playback_session_can_be_cancelled_by_http_delete(monkeypatch):
    _configure_playback(monkeypatch)
    monkeypatch.setattr(main, "call_home_assistant_play_media", lambda *args: None)
    client = TestClient(app)

    created = client.post(
        "/playback/sessions",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "client_id": "voice-pe",
            "media_player_entity_id": "media_player.beosound2",
            "sample_rate": 24000,
            "frame_duration_ms": 60,
        },
    ).json()

    cancelled = client.delete(f"/playback/sessions/{created['session_id']}")

    assert cancelled.status_code == 200
    assert cancelled.json() == {"cancelled": True}
    assert client.get(urlsplit(created["stream_url"]).path).status_code == 410


def test_playback_stream_disconnect_marks_session_failed_without_waiting_for_timeout():
    session = PlaybackSession(
        session_id="session-1",
        device_id="aa:bb:cc:dd:ee:ff",
        client_id="voice-pe",
        media_player_entity_id="media_player.beosound2",
        stream_url="http://gateway.local/playback/sessions/session-1/stream.ogg",
        upload_url="ws://gateway.local/playback/sessions/session-1/upload",
        sample_rate=24000,
        frame_duration_ms=60,
        initial_buffer_ms=300,
        timeout_ms=60000,
    )

    stream = session.iter_ogg()
    assert next(stream).startswith(b"OggS")
    stream.close()

    assert session.terminal is True
    assert session.failed is True
    assert session.fail_reason == "stream_disconnected"


def test_playback_session_store_prunes_old_terminal_sessions():
    store = PlaybackSessionStore(terminal_ttl_seconds=3600)
    request = PlaybackSessionRequest(
        device_id="aa:bb:cc:dd:ee:ff",
        client_id="voice-pe",
        media_player_entity_id="media_player.beosound2",
        sample_rate=24000,
        frame_duration_ms=60,
    )
    session = store.create(
        request,
        session_id="session-1",
        stream_url="http://gateway.local/playback/sessions/session-1/stream.ogg",
        upload_url="ws://gateway.local/playback/sessions/session-1/upload",
    )
    session.created_at = 100
    session.finish()
    session.terminal_at = 100

    store.prune_terminal(now=3701)

    assert store.get("session-1") is None


def test_ogg_opus_muxer_uses_48khz_granule_position():
    muxer = OggOpusMuxer(sample_rate=24000, frame_duration_ms=60, serial=1)
    chunks = list(muxer.headers())
    chunks.append(muxer.audio_page(b"one"))
    chunks.append(muxer.audio_page(b"two", end_of_stream=True))
    data = b"".join(chunks)

    assert data.count(b"OggS") == 4
    assert b"OpusHead" in data
    assert b"OpusTags" in data
    assert (2880).to_bytes(8, "little") in data
    assert (5760).to_bytes(8, "little") in data
