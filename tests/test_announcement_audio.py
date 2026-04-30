import pytest

from app.announcement_audio import (
    AnnouncementDisabledError,
    TtsEmptyAudioError,
    UnsupportedAnnouncementProviderError,
    synthesize_announcement_frames,
)
from app.config import AnnouncementConfig


class FakeProvider:
    def __init__(self, pcm: bytes):
        self.pcm = pcm
        self.text = ""

    def synthesize_pcm(self, text: str) -> bytes:
        self.text = text
        return self.pcm


def test_synthesize_announcement_frames_encodes_pcm_to_opus_frames(monkeypatch):
    provider = FakeProvider(b"\x00\x00" * 960)
    monkeypatch.setattr(
        "app.announcement_audio.encode_raw_opus_frames",
        lambda pcm: [b"opus"] if pcm else [],
    )

    frames = synthesize_announcement_frames(
        "现在房间温度较高",
        AnnouncementConfig(provider="doubao"),
        provider_factory=lambda config: provider,
    )

    assert provider.text == "现在房间温度较高"
    assert len(frames) == 1
    assert frames[0] == b"opus"


def test_synthesize_announcement_frames_rejects_disabled_mode():
    with pytest.raises(AnnouncementDisabledError, match="disabled"):
        synthesize_announcement_frames(
            "打开空调",
            AnnouncementConfig(enabled=False),
            provider_factory=lambda config: FakeProvider(b"pcm"),
        )


def test_synthesize_announcement_frames_rejects_unimplemented_provider():
    with pytest.raises(UnsupportedAnnouncementProviderError, match="unsupported"):
        synthesize_announcement_frames("打开空调", AnnouncementConfig(provider="bailian"))


def test_synthesize_announcement_frames_rejects_empty_audio():
    with pytest.raises(TtsEmptyAudioError, match="no audio"):
        synthesize_announcement_frames(
            "打开空调",
            AnnouncementConfig(provider="doubao"),
            provider_factory=lambda config: FakeProvider(b""),
        )
