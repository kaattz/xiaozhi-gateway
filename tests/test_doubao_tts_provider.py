import json
import struct

import pytest

from app.config import AnnouncementDoubaoConfig
from app.tts_providers.doubao import (
    DoubaoAuthenticationError,
    DoubaoTtsError,
    DoubaoTtsProvider,
    DoubaoTtsTimeout,
    MissingDoubaoApiKeyError,
)
from app.tts_providers.doubao import Event, parse_tts2_frame
from websockets.exceptions import WebSocketException


class FakeWebSocket:
    def __init__(self, messages: list[bytes] | None = None, error: Exception | None = None):
        self.sent: list[bytes] = []
        self.closed = False
        self._messages = list(messages or [])
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True

    def send(self, payload: bytes) -> None:
        self.sent.append(payload)

    def recv(self, timeout: float | None = None) -> bytes:
        if self._error is not None:
            raise self._error
        if not self._messages:
            raise AssertionError("unexpected recv")
        return self._messages.pop(0)


def make_frame(
    event: Event,
    payload: bytes = b"{}",
    session_id: str = "",
    message_type: int = 0x1,
) -> bytes:
    frame = bytearray([0x11, (message_type << 4) | 0x4, 0x10, 0x00])
    frame.extend(struct.pack(">i", int(event)))
    if session_id:
        session_id_bytes = session_id.encode()
        frame.extend(struct.pack(">I", len(session_id_bytes)))
        frame.extend(session_id_bytes)
    frame.extend(struct.pack(">I", len(payload)))
    frame.extend(payload)
    return bytes(frame)


def make_server_connection_frame(event: Event, payload: bytes = b"{}") -> bytes:
    frame = bytearray([0x11, 0x94, 0x10, 0x00])
    frame.extend(struct.pack(">i", int(event)))
    connect_id = b"connect-a"
    frame.extend(struct.pack(">I", len(connect_id)))
    frame.extend(connect_id)
    frame.extend(struct.pack(">I", len(payload)))
    frame.extend(payload)
    return bytes(frame)


def test_parse_tts2_frame_accepts_real_server_response_headers():
    connection_started = parse_tts2_frame(
        make_server_connection_frame(Event.CONNECTION_STARTED)
    )
    session_started = parse_tts2_frame(
        make_frame(Event.SESSION_STARTED, session_id="session-a", message_type=0x9)
    )
    audio = parse_tts2_frame(
        make_frame(
            Event.TTS_RESPONSE,
            b"\x01\x00\x02\x00",
            session_id="session-a",
            message_type=0xB,
        )
    )

    assert connection_started.event == Event.CONNECTION_STARTED
    assert connection_started.payload == b"{}"
    assert session_started.event == Event.SESSION_STARTED
    assert session_started.session_id == "session-a"
    assert audio.event == Event.TTS_RESPONSE
    assert audio.payload == b"\x01\x00\x02\x00"


def test_doubao_provider_sends_tts2_v3_events_and_returns_pcm():
    ws = FakeWebSocket(
        [
            make_server_connection_frame(Event.CONNECTION_STARTED),
            make_frame(Event.SESSION_STARTED, session_id="session-a", message_type=0x9),
            make_frame(
                Event.TTS_RESPONSE,
                b"\x01\x00\x02\x00",
                session_id="session-a",
                message_type=0xB,
            ),
            make_frame(Event.SESSION_FINISHED, session_id="session-a", message_type=0x9),
        ]
    )
    captured = {}

    def connect_factory(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return ws

    provider = DoubaoTtsProvider(
        AnnouncementDoubaoConfig(
            app_id="app-id",
            access_key="access-key",
            resource_id="seed-tts-2.0",
            voice="voice-a",
        ),
        connect_factory=connect_factory,
        session_id_factory=lambda: "session-a",
        connect_id_factory=lambda: "connect-a",
    )

    pcm = provider.synthesize_pcm("现在房间温度较高")

    assert pcm == b"\x01\x00\x02\x00"
    assert captured["url"] == "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
    assert captured["kwargs"]["additional_headers"] == {
        "X-Api-App-Key": "app-id",
        "X-Api-Access-Key": "access-key",
        "X-Api-Resource-Id": "seed-tts-2.0",
        "X-Api-Connect-Id": "connect-a",
    }
    sent_frames = [parse_tts2_frame(payload) for payload in ws.sent]
    assert [frame.event for frame in sent_frames] == [
        Event.START_CONNECTION,
        Event.START_SESSION,
        Event.TASK_REQUEST,
        Event.FINISH_SESSION,
        Event.FINISH_CONNECTION,
    ]
    assert json.loads(sent_frames[1].payload.decode())["req_params"] == {
        "speaker": "voice-a",
        "audio_params": {
            "format": "pcm",
            "sample_rate": 16000,
            "speech_rate": 0,
        },
    }
    assert json.loads(sent_frames[2].payload.decode())["req_params"]["text"] == "现在房间温度较高"
    assert ws.closed is True


def test_doubao_provider_maps_fast_speech_speed_to_tts2_speech_rate():
    ws = FakeWebSocket(
        [
            make_server_connection_frame(Event.CONNECTION_STARTED),
            make_frame(Event.SESSION_STARTED, session_id="session-a", message_type=0x9),
            make_frame(Event.TTS_RESPONSE, b"\x01\x00", session_id="session-a", message_type=0xB),
            make_frame(Event.SESSION_FINISHED, session_id="session-a", message_type=0x9),
        ]
    )
    provider = DoubaoTtsProvider(
        AnnouncementDoubaoConfig(
            app_id="app-id",
            access_key="access-key",
            voice="voice-a",
            speech_speed="快速",
        ),
        connect_factory=lambda url, **kwargs: ws,
        session_id_factory=lambda: "session-a",
        connect_id_factory=lambda: "connect-a",
    )

    provider.synthesize_pcm("现在房间温度较高")

    start_session = parse_tts2_frame(ws.sent[1])
    assert json.loads(start_session.payload.decode())["req_params"]["audio_params"][
        "speech_rate"
    ] == 20


def test_doubao_provider_requires_v3_credentials():
    provider = DoubaoTtsProvider(AnnouncementDoubaoConfig(app_id="", access_key=""))

    with pytest.raises(MissingDoubaoApiKeyError, match="app_id/access_key"):
        provider.synthesize_pcm("打开空调")


def test_doubao_provider_maps_authentication_error_without_leaking_key():
    ws = FakeWebSocket(
        [
            make_server_connection_frame(
                Event.CONNECTION_FAILED,
                json.dumps({"code": 401, "message": "unauthorized"}).encode(),
            )
        ]
    )
    provider = DoubaoTtsProvider(
        AnnouncementDoubaoConfig(app_id="app-id", access_key="access-key"),
        connect_factory=lambda url, **kwargs: ws,
        connect_id_factory=lambda: "connect-a",
    )

    with pytest.raises(DoubaoAuthenticationError) as error:
        provider.synthesize_pcm("打开空调")

    assert "access-key" not in str(error.value)


def test_doubao_provider_maps_timeout():
    provider = DoubaoTtsProvider(
        AnnouncementDoubaoConfig(app_id="app-id", access_key="access-key"),
        connect_factory=lambda url, **kwargs: FakeWebSocket(error=TimeoutError()),
    )

    with pytest.raises(DoubaoTtsTimeout, match="timeout"):
        provider.synthesize_pcm("打开空调")


def test_doubao_provider_preserves_safe_websocket_error_detail():
    provider = DoubaoTtsProvider(
        AnnouncementDoubaoConfig(app_id="app-id", access_key="access-key"),
        connect_factory=lambda url, **kwargs: (_ for _ in ()).throw(
            WebSocketException("proxy refused connection")
        ),
    )

    with pytest.raises(DoubaoTtsError) as error:
        provider.synthesize_pcm("打开空调")

    assert str(error.value) == (
        "doubao websocket failed: WebSocketException: proxy refused connection"
    )
    assert "access-key" not in str(error.value)


def test_doubao_provider_maps_websocket_authentication_error():
    provider = DoubaoTtsProvider(
        AnnouncementDoubaoConfig(app_id="app-id", access_key="access-key"),
        connect_factory=lambda url, **kwargs: (_ for _ in ()).throw(
            WebSocketException("server rejected WebSocket connection: HTTP 403")
        ),
    )

    with pytest.raises(DoubaoAuthenticationError) as error:
        provider.synthesize_pcm("打开空调")

    assert "HTTP 403" in str(error.value)
    assert "access-key" not in str(error.value)
