import json
from io import BytesIO

import pytest

from app.config import RemoteTextConfig
from app.remote_text_audio import (
    encode_raw_opus_frames,
    synthesize_wav_from_wyoming,
    synthesize_remote_text_wav,
)


def test_encode_raw_opus_frames_encodes_one_60ms_packet_for_960_samples():
    pcm = b"\x00\x00" * 960

    frames = encode_raw_opus_frames(pcm)

    assert len(frames) == 1
    assert frames[0]


class FakeWyomingSocket:
    def __init__(self, events: list[tuple[dict, bytes]]):
        self.sent = b""
        self.closed = False
        payload = b"".join(
            json.dumps(header).encode("utf-8") + b"\n" + body
            for header, body in events
        )
        self._reader = BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True

    def settimeout(self, timeout):
        self.timeout = timeout

    def sendall(self, data):
        self.sent += data

    def makefile(self, mode):
        return self._reader


def test_synthesize_wav_from_wyoming_sends_synthesize_and_returns_wav(monkeypatch):
    fake_socket = FakeWyomingSocket(
        [
            ({"type": "audio-start", "data": {"rate": 22050, "width": 2, "channels": 1}}, b""),
            (
                {
                    "type": "audio-chunk",
                    "data": {"rate": 22050, "width": 2, "channels": 1},
                    "payload_length": 4,
                },
                b"\x01\x00\x02\x00",
            ),
            ({"type": "audio-stop"}, b""),
        ]
    )
    monkeypatch.setattr(
        "app.remote_text_audio.socket.create_connection",
        lambda address, timeout: fake_socket,
    )

    wav = synthesize_wav_from_wyoming("打开空调", "core-piper", 10200)

    assert b'"type":"synthesize"' in fake_socket.sent
    assert b'"text":"\\u6253\\u5f00\\u7a7a\\u8c03"' in fake_socket.sent
    assert wav.startswith(b"RIFF")
    assert fake_socket.closed


def test_synthesize_remote_text_wav_uses_wyoming_provider(monkeypatch):
    monkeypatch.setattr(
        "app.remote_text_audio.synthesize_wav_from_wyoming",
        lambda text, host, port: b"wav",
    )

    wav = synthesize_remote_text_wav(
        "打开空调",
        RemoteTextConfig(provider="wyoming", wyoming_host="core-piper", wyoming_port=10200),
    )

    assert wav == b"wav"


def test_synthesize_remote_text_wav_rejects_local_provider(monkeypatch):
    monkeypatch.setattr(
        "app.remote_text_audio.synthesize_wav",
        lambda *args: b"wav",
        raising=False,
    )

    with pytest.raises(RuntimeError, match="unsupported remote text provider: local"):
        synthesize_remote_text_wav("打开空调", RemoteTextConfig(provider="local"))
