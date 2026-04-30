import base64
import json

import pytest

from app.config import AnnouncementDoubaoConfig
from app.tts_providers.doubao import (
    DoubaoAuthenticationError,
    DoubaoTtsProvider,
    DoubaoTtsTimeout,
    MissingDoubaoApiKeyError,
)


class FakeWebSocket:
    def __init__(self, messages: list[dict] | None = None, error: Exception | None = None):
        self.sent: list[dict] = []
        self.closed = False
        self._messages = list(messages or [])
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True

    def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))

    def recv(self, timeout: float | None = None) -> str:
        if self._error is not None:
            raise self._error
        if not self._messages:
            raise AssertionError("unexpected recv")
        return json.dumps(self._messages.pop(0))


def test_doubao_provider_sends_realtime_events_and_returns_pcm():
    audio = base64.b64encode(b"\x01\x00\x02\x00").decode("ascii")
    ws = FakeWebSocket(
        [
            {"type": "response.audio.delta", "delta": audio},
            {"type": "response.audio.done"},
        ]
    )
    captured = {}

    def connect_factory(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return ws

    provider = DoubaoTtsProvider(
        AnnouncementDoubaoConfig(api_key="secret", voice="voice-a"),
        connect_factory=connect_factory,
    )

    pcm = provider.synthesize_pcm("现在房间温度较高")

    assert pcm == b"\x01\x00\x02\x00"
    assert captured["url"] == "wss://ai-gateway.vei.volces.com/v1/realtime?model=doubao-tts"
    assert captured["kwargs"]["additional_headers"] == {"Authorization": "Bearer secret"}
    assert [event["type"] for event in ws.sent] == [
        "tts_session.update",
        "input_text.append",
        "input_text.done",
    ]
    assert ws.sent[0]["session"] == {
        "voice": "voice-a",
        "output_audio_format": "pcm",
        "output_audio_sample_rate": 16000,
        "text_to_speech": {"model": "doubao-tts"},
    }
    assert ws.sent[1]["delta"] == "现在房间温度较高"
    assert ws.closed is True


def test_doubao_provider_requires_api_key():
    provider = DoubaoTtsProvider(AnnouncementDoubaoConfig(api_key=""))

    with pytest.raises(MissingDoubaoApiKeyError, match="api key"):
        provider.synthesize_pcm("打开空调")


def test_doubao_provider_maps_authentication_error_without_leaking_key():
    ws = FakeWebSocket(
        [
            {
                "type": "error",
                "error": {"code": "401", "message": "unauthorized"},
            }
        ]
    )
    provider = DoubaoTtsProvider(
        AnnouncementDoubaoConfig(api_key="secret"),
        connect_factory=lambda url, **kwargs: ws,
    )

    with pytest.raises(DoubaoAuthenticationError) as error:
        provider.synthesize_pcm("打开空调")

    assert "secret" not in str(error.value)


def test_doubao_provider_maps_timeout():
    provider = DoubaoTtsProvider(
        AnnouncementDoubaoConfig(api_key="secret"),
        connect_factory=lambda url, **kwargs: FakeWebSocket(error=TimeoutError()),
    )

    with pytest.raises(DoubaoTtsTimeout, match="timeout"):
        provider.synthesize_pcm("打开空调")
