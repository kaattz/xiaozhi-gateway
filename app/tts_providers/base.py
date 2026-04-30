from typing import Protocol


class TtsProvider(Protocol):
    def synthesize_pcm(self, text: str) -> bytes:
        ...


class TtsProviderError(RuntimeError):
    pass


class MissingTtsApiKeyError(TtsProviderError):
    pass


class TtsAuthenticationError(TtsProviderError):
    pass


class TtsTimeoutError(TtsProviderError):
    pass


class TtsEmptyAudioError(TtsProviderError):
    pass
