from collections.abc import Callable

from app.audio_frames import (
    FRAME_DURATION_MS,
    SAMPLE_RATE,
    encode_raw_opus_frames,
)
from app.config import AnnouncementConfig
from app.tts_providers.base import (
    MissingTtsApiKeyError,
    TtsAuthenticationError,
    TtsEmptyAudioError,
    TtsProvider,
    TtsProviderError,
    TtsTimeoutError,
)
from app.tts_providers.doubao import DoubaoTtsProvider


class AnnouncementDisabledError(RuntimeError):
    pass


class UnsupportedAnnouncementProviderError(RuntimeError):
    pass


ProviderFactory = Callable[[AnnouncementConfig], TtsProvider]


def build_tts_provider(config: AnnouncementConfig) -> TtsProvider:
    provider = config.provider.strip().lower()
    if provider == "doubao":
        return DoubaoTtsProvider(config.doubao)
    raise UnsupportedAnnouncementProviderError(
        f"unsupported announcement provider: {provider}"
    )


def synthesize_announcement_frames(
    text: str,
    config: AnnouncementConfig,
    provider_factory: ProviderFactory | None = None,
) -> list[bytes]:
    if not config.enabled:
        raise AnnouncementDisabledError("announcement disabled")

    provider_name = config.provider.strip().lower()
    if provider_name != "doubao":
        raise UnsupportedAnnouncementProviderError(
            f"unsupported announcement provider: {provider_name}"
        )
    if config.frame_format != "opus":
        raise UnsupportedAnnouncementProviderError(
            f"unsupported announcement frame format: {config.frame_format}"
        )
    if config.frame_duration_ms != FRAME_DURATION_MS:
        raise UnsupportedAnnouncementProviderError(
            f"unsupported announcement frame duration: {config.frame_duration_ms}"
        )
    if config.doubao.sample_rate != SAMPLE_RATE:
        raise UnsupportedAnnouncementProviderError(
            f"unsupported doubao sample rate: {config.doubao.sample_rate}"
        )

    provider = provider_factory(config) if provider_factory else build_tts_provider(config)
    pcm = provider.synthesize_pcm(text)
    if not pcm:
        raise TtsEmptyAudioError("tts produced no audio")

    frames = encode_raw_opus_frames(pcm)
    if not frames:
        raise TtsEmptyAudioError("opus encoding produced no frames")
    return frames
