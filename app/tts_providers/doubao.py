import base64
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from app.config import AnnouncementDoubaoConfig
from app.tts_providers.base import (
    MissingTtsApiKeyError,
    TtsAuthenticationError,
    TtsEmptyAudioError,
    TtsProviderError,
    TtsTimeoutError,
)


DOUBAO_REALTIME_URL = "wss://ai-gateway.vei.volces.com/v1/realtime"
DOUBAO_TIMEOUT_SECONDS = 10


class DoubaoTtsError(TtsProviderError):
    pass


class MissingDoubaoApiKeyError(MissingTtsApiKeyError):
    pass


class DoubaoAuthenticationError(TtsAuthenticationError):
    pass


class DoubaoTtsTimeout(TtsTimeoutError):
    pass


ConnectFactory = Callable[..., Any]


class DoubaoTtsProvider:
    def __init__(
        self,
        config: AnnouncementDoubaoConfig,
        connect_factory: ConnectFactory = connect,
        timeout_seconds: int = DOUBAO_TIMEOUT_SECONDS,
    ) -> None:
        self._config = config
        self._connect_factory = connect_factory
        self._timeout_seconds = timeout_seconds

    def synthesize_pcm(self, text: str) -> bytes:
        api_key = self._config.api_key.strip()
        if not api_key:
            raise MissingDoubaoApiKeyError("doubao api key is not configured")

        model = self._config.model.strip()
        url = f"{DOUBAO_REALTIME_URL}?model={quote(model, safe='')}"
        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            with self._connect_factory(
                url,
                additional_headers=headers,
                open_timeout=self._timeout_seconds,
                close_timeout=self._timeout_seconds,
            ) as ws:
                self._send_session_update(ws)
                self._send_text(ws, text)
                return self._read_pcm(ws)
        except TimeoutError as exc:
            raise DoubaoTtsTimeout("doubao synthesis timeout") from exc
        except WebSocketException as exc:
            raise DoubaoTtsError("doubao websocket failed") from exc

    def _send_session_update(self, ws: Any) -> None:
        ws.send(
            json.dumps(
                {
                    "type": "tts_session.update",
                    "session": {
                        "voice": self._config.voice.strip(),
                        "output_audio_format": "pcm",
                        "output_audio_sample_rate": self._config.sample_rate,
                        "text_to_speech": {"model": self._config.model.strip()},
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )

    def _send_text(self, ws: Any, text: str) -> None:
        for event in (
            {"type": "input_text.append", "delta": text},
            {"type": "input_text.done"},
        ):
            ws.send(json.dumps(event, ensure_ascii=False, separators=(",", ":")))

    def _read_pcm(self, ws: Any) -> bytes:
        pcm = bytearray()
        while True:
            raw = ws.recv(timeout=self._timeout_seconds)
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            event = json.loads(raw)
            event_type = event.get("type")

            if event_type in {"error", "response.error"}:
                raise self._map_error_event(event)

            if event_type == "response.audio.delta":
                delta = event.get("delta")
                if not isinstance(delta, str) or not delta:
                    raise DoubaoTtsError("doubao audio delta is empty")
                pcm.extend(base64.b64decode(delta))
                continue

            if event_type in {"response.audio.done", "response.done"}:
                break

        if not pcm:
            raise TtsEmptyAudioError("doubao produced no audio")
        return bytes(pcm)

    def _map_error_event(self, event: dict[str, Any]) -> TtsProviderError:
        error = event.get("error") or {}
        code = str(error.get("code") or event.get("code") or "")
        message = str(error.get("message") or event.get("message") or "doubao tts error")
        normalized = f"{code} {message}".lower()
        if "401" in normalized or "403" in normalized or "auth" in normalized:
            return DoubaoAuthenticationError("doubao authentication failed")
        return DoubaoTtsError("doubao tts error")
