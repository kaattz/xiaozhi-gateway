import json
import struct
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

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


DOUBAO_TTS2_V3_URL = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
DOUBAO_TIMEOUT_SECONDS = 10
PROTOCOL_VERSION = 0x1
HEADER_SIZE_WORDS = 0x1
MESSAGE_TYPE_FULL_CLIENT_REQUEST = 0x1
MESSAGE_TYPE_FULL_SERVER_RESPONSE = 0x9
MESSAGE_TYPE_AUDIO_ONLY_SERVER = 0xB
MESSAGE_TYPE_FLAG_WITH_EVENT = 0x4
SERIALIZATION_JSON = 0x1
COMPRESSION_NONE = 0x0
HEADER = bytes(
    [
        (PROTOCOL_VERSION << 4) | HEADER_SIZE_WORDS,
        (MESSAGE_TYPE_FULL_CLIENT_REQUEST << 4) | MESSAGE_TYPE_FLAG_WITH_EVENT,
        (SERIALIZATION_JSON << 4) | COMPRESSION_NONE,
        0x00,
    ]
)
MAX_ERROR_DETAIL_LENGTH = 300


class Event(IntEnum):
    START_CONNECTION = 1
    FINISH_CONNECTION = 2
    CONNECTION_STARTED = 50
    CONNECTION_FAILED = 51
    CONNECTION_FINISHED = 52
    START_SESSION = 100
    FINISH_SESSION = 102
    SESSION_STARTED = 150
    SESSION_FAILED = 153
    SESSION_FINISHED = 152
    TASK_REQUEST = 200
    TTS_SENTENCE_START = 350
    TTS_SENTENCE_END = 351
    TTS_RESPONSE = 352


EVENTS_WITH_SESSION_ID = {
    Event.START_SESSION,
    Event.FINISH_SESSION,
    Event.SESSION_STARTED,
    Event.SESSION_FAILED,
    Event.SESSION_FINISHED,
    Event.TASK_REQUEST,
    Event.TTS_SENTENCE_START,
    Event.TTS_SENTENCE_END,
    Event.TTS_RESPONSE,
}

EVENTS_WITH_CONNECTION_ID = {
    Event.CONNECTION_STARTED,
    Event.CONNECTION_FAILED,
    Event.CONNECTION_FINISHED,
}


@dataclass(frozen=True)
class Tts2Frame:
    event: Event
    payload: bytes
    session_id: str = ""


class DoubaoTtsError(TtsProviderError):
    pass


class MissingDoubaoApiKeyError(MissingTtsApiKeyError):
    pass


class DoubaoAuthenticationError(TtsAuthenticationError):
    pass


class DoubaoTtsTimeout(TtsTimeoutError):
    pass


ConnectFactory = Callable[..., Any]
IdFactory = Callable[[], str]


def make_tts2_frame(
    event: Event,
    payload: bytes = b"{}",
    session_id: str = "",
) -> bytes:
    frame = bytearray(HEADER)
    frame.extend(struct.pack(">i", int(event)))
    if session_id:
        session_id_bytes = session_id.encode("utf-8")
        frame.extend(struct.pack(">I", len(session_id_bytes)))
        frame.extend(session_id_bytes)
    frame.extend(struct.pack(">I", len(payload)))
    frame.extend(payload)
    return bytes(frame)


def parse_tts2_frame(frame: bytes) -> Tts2Frame:
    if not isinstance(frame, bytes):
        raise DoubaoTtsError("doubao tts2 frame is not bytes")
    if len(frame) < 4:
        raise DoubaoTtsError("doubao tts2 frame is too short")

    version = frame[0] >> 4
    header_size_words = frame[0] & 0x0F
    message_type = frame[1] >> 4
    message_type_flag = frame[1] & 0x0F
    header_size = header_size_words * 4
    if version != PROTOCOL_VERSION or header_size < 4 or len(frame) < header_size + 4:
        raise DoubaoTtsError("doubao tts2 frame header is invalid")
    if message_type_flag != MESSAGE_TYPE_FLAG_WITH_EVENT:
        raise DoubaoTtsError("doubao tts2 frame missing event flag")
    if message_type not in {
        MESSAGE_TYPE_FULL_CLIENT_REQUEST,
        MESSAGE_TYPE_FULL_SERVER_RESPONSE,
        MESSAGE_TYPE_AUDIO_ONLY_SERVER,
    }:
        raise DoubaoTtsError("doubao tts2 frame message type is unsupported")

    try:
        event = Event(struct.unpack(">i", frame[header_size : header_size + 4])[0])
    except ValueError as exc:
        raise DoubaoTtsError("doubao tts2 frame event is unsupported") from exc
    offset = header_size + 4
    session_id = ""
    if event in EVENTS_WITH_SESSION_ID:
        if len(frame) < offset + 4:
            raise DoubaoTtsError("doubao tts2 frame missing session id length")
        session_id_len = struct.unpack(">I", frame[offset : offset + 4])[0]
        offset += 4
        session_id = frame[offset : offset + session_id_len].decode("utf-8")
        offset += session_id_len

    if event in EVENTS_WITH_CONNECTION_ID:
        if len(frame) < offset + 4:
            raise DoubaoTtsError("doubao tts2 frame missing connection id length")
        connection_id_len = struct.unpack(">I", frame[offset : offset + 4])[0]
        offset += 4 + connection_id_len

    if len(frame) < offset + 4:
        raise DoubaoTtsError("doubao tts2 frame missing payload length")
    payload_len = struct.unpack(">I", frame[offset : offset + 4])[0]
    offset += 4
    payload = frame[offset : offset + payload_len]
    if len(payload) != payload_len:
        raise DoubaoTtsError("doubao tts2 frame payload is truncated")
    return Tts2Frame(event=event, session_id=session_id, payload=payload)


class DoubaoTtsProvider:
    def __init__(
        self,
        config: AnnouncementDoubaoConfig,
        connect_factory: ConnectFactory = connect,
        timeout_seconds: int = DOUBAO_TIMEOUT_SECONDS,
        session_id_factory: IdFactory | None = None,
        connect_id_factory: IdFactory | None = None,
    ) -> None:
        self._config = config
        self._connect_factory = connect_factory
        self._timeout_seconds = timeout_seconds
        self._session_id_factory = session_id_factory or uuid.uuid4
        self._connect_id_factory = connect_id_factory or uuid.uuid4

    def synthesize_pcm(self, text: str) -> bytes:
        app_id = self._config.app_id.strip()
        access_key = self._config.access_key.strip()
        if not app_id or not access_key:
            raise MissingDoubaoApiKeyError("doubao app_id/access_key is not configured")

        session_id = str(self._session_id_factory()).replace("-", "")
        headers = {
            "X-Api-App-Key": app_id,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": self._config.resource_id.strip(),
            "X-Api-Connect-Id": str(self._connect_id_factory()),
        }

        try:
            with self._connect_factory(
                DOUBAO_TTS2_V3_URL,
                additional_headers=headers,
                open_timeout=self._timeout_seconds,
                close_timeout=self._timeout_seconds,
            ) as ws:
                self._start_connection(ws)
                self._start_session(ws, session_id)
                ws.send(self._task_request_frame(session_id, text))
                ws.send(make_tts2_frame(Event.FINISH_SESSION, session_id=session_id))
                pcm = self._read_pcm(ws)
                ws.send(make_tts2_frame(Event.FINISH_CONNECTION))
        except TimeoutError as exc:
            raise DoubaoTtsTimeout("doubao synthesis timeout") from exc
        except WebSocketException as exc:
            detail = self._safe_exception_detail(exc, app_id, access_key)
            if self._is_authentication_detail(detail):
                raise DoubaoAuthenticationError(
                    f"doubao websocket authentication failed: {detail}"
                ) from exc
            raise DoubaoTtsError(f"doubao websocket failed: {detail}") from exc
        except OSError as exc:
            detail = self._safe_exception_detail(exc, app_id, access_key)
            raise DoubaoTtsError(f"doubao network failed: {detail}") from exc

        if not pcm:
            raise TtsEmptyAudioError("doubao produced no audio")
        return pcm

    def _start_connection(self, ws: Any) -> None:
        ws.send(make_tts2_frame(Event.START_CONNECTION))
        frame = parse_tts2_frame(ws.recv(timeout=self._timeout_seconds))
        if frame.event == Event.CONNECTION_FAILED:
            raise self._map_error_frame(frame)
        if frame.event != Event.CONNECTION_STARTED:
            raise DoubaoTtsError("doubao connection did not start")

    def _start_session(self, ws: Any, session_id: str) -> None:
        payload = json.dumps(
            {
                "event": int(Event.START_SESSION),
                "req_params": {
                    "speaker": self._config.voice.strip(),
                    "audio_params": {
                        "format": "pcm",
                        "sample_rate": self._config.sample_rate,
                    },
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        ws.send(make_tts2_frame(Event.START_SESSION, payload, session_id))
        frame = parse_tts2_frame(ws.recv(timeout=self._timeout_seconds))
        if frame.event == Event.SESSION_FAILED:
            raise self._map_error_frame(frame)
        if frame.event != Event.SESSION_STARTED:
            raise DoubaoTtsError("doubao session did not start")

    def _task_request_frame(self, session_id: str, text: str) -> bytes:
        payload = json.dumps(
            {
                "event": int(Event.TASK_REQUEST),
                "req_params": {"text": text},
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return make_tts2_frame(Event.TASK_REQUEST, payload, session_id)

    def _read_pcm(self, ws: Any) -> bytes:
        pcm = bytearray()
        while True:
            frame = parse_tts2_frame(ws.recv(timeout=self._timeout_seconds))
            if frame.event == Event.TTS_RESPONSE:
                pcm.extend(frame.payload)
                continue
            if frame.event in {Event.TTS_SENTENCE_START, Event.TTS_SENTENCE_END}:
                continue
            if frame.event == Event.SESSION_FAILED:
                raise self._map_error_frame(frame)
            if frame.event == Event.SESSION_FINISHED:
                break
        return bytes(pcm)

    def _map_error_frame(self, frame: Tts2Frame) -> TtsProviderError:
        code = ""
        message = ""
        if frame.payload:
            try:
                body = json.loads(frame.payload.decode("utf-8"))
                code = str(body.get("code") or body.get("Code") or "")
                message = str(body.get("message") or body.get("Message") or "")
            except (UnicodeDecodeError, json.JSONDecodeError):
                message = frame.payload.decode("utf-8", errors="ignore")
        normalized = f"{code} {message}".lower()
        if "401" in normalized or "403" in normalized or "auth" in normalized:
            return DoubaoAuthenticationError("doubao authentication failed")
        return DoubaoTtsError("doubao tts error")

    def _safe_exception_detail(
        self,
        exc: Exception,
        app_id: str,
        access_key: str,
    ) -> str:
        message = str(exc).replace("\r", " ").replace("\n", " ").strip()
        detail = type(exc).__name__
        if message:
            detail = f"{detail}: {message}"
        for secret in (app_id, access_key):
            if secret:
                detail = detail.replace(secret, "<redacted>")
        if len(detail) > MAX_ERROR_DETAIL_LENGTH:
            detail = detail[:MAX_ERROR_DETAIL_LENGTH] + "..."
        return detail

    def _is_authentication_detail(self, detail: str) -> bool:
        normalized = detail.lower()
        return any(
            marker in normalized
            for marker in ("401", "403", "auth", "unauthorized", "forbidden")
        )
