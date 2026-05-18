import json
import queue
import socket
import struct
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Iterator
from urllib.parse import urlsplit

from app.config import PlaybackConfig
from app.models import PlaybackSessionRequest


def _ogg_crc(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value << 24
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ 0x04C11DB7) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    return crc


class OggOpusMuxer:
    def __init__(self, *, sample_rate: int, frame_duration_ms: int, serial: int | None = None) -> None:
        self.sample_rate = sample_rate
        self.frame_duration_ms = frame_duration_ms
        self.serial = serial if serial is not None else uuid.uuid4().int & 0xFFFFFFFF
        self.sequence = 0
        self.granule_position = 0

    def headers(self) -> Iterator[bytes]:
        opus_head = (
            b"OpusHead"
            + bytes([1, 1])
            + struct.pack("<H", 0)
            + struct.pack("<I", self.sample_rate)
            + struct.pack("<h", 0)
            + bytes([0])
        )
        vendor = b"xiaozhi-gateway"
        opus_tags = b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)
        yield self._page(opus_head, header_type=0x02, granule_position=0)
        yield self._page(opus_tags, header_type=0x00, granule_position=0)

    def audio_page(self, packet: bytes, *, end_of_stream: bool = False) -> bytes:
        self.granule_position += int(48000 * self.frame_duration_ms / 1000)
        return self._page(
            packet,
            header_type=0x04 if end_of_stream else 0x00,
            granule_position=self.granule_position,
        )

    def end_page(self) -> bytes:
        return self._page(b"", header_type=0x04, granule_position=self.granule_position)

    def _page(self, packet: bytes, *, header_type: int, granule_position: int) -> bytes:
        segments: list[int] = []
        remaining = len(packet)
        while remaining >= 255:
            segments.append(255)
            remaining -= 255
        segments.append(remaining)

        header = (
            b"OggS"
            + bytes([0, header_type])
            + struct.pack("<Q", granule_position)
            + struct.pack("<I", self.serial)
            + struct.pack("<I", self.sequence)
            + struct.pack("<I", 0)
            + bytes([len(segments)])
            + bytes(segments)
        )
        page = header + packet
        checksum = _ogg_crc(page)
        page = page[:22] + struct.pack("<I", checksum) + page[26:]
        self.sequence += 1
        return page


@dataclass
class PlaybackSession:
    session_id: str
    device_id: str
    client_id: str
    media_player_entity_id: str
    stream_url: str
    upload_url: str
    sample_rate: int
    frame_duration_ms: int
    initial_buffer_ms: int
    timeout_ms: int
    created_at: float = field(default_factory=time.time)
    frame_queue: queue.Queue[bytes | None] = field(default_factory=queue.Queue)
    status_queue: queue.Queue[dict] = field(default_factory=queue.Queue)
    buffered_audio_ms: int = 0
    ha_play_media_called: bool = False
    input_closed: bool = False
    stream_started: bool = False
    terminal: bool = False
    terminal_at: float | None = None
    failed: bool = False
    cancelled: bool = False
    fail_reason: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return self.device_id, self.client_id

    def add_frame(self, frame: bytes) -> bool:
        if self.terminal:
            return False
        self.frame_queue.put(bytes(frame))
        self.buffered_audio_ms += self.frame_duration_ms
        return self.buffered_audio_ms >= self.initial_buffer_ms and not self.ha_play_media_called

    def close_input(self) -> None:
        if not self.input_closed:
            self.input_closed = True
            self.frame_queue.put(None)

    def mark_ha_play_media_called(self) -> None:
        self.ha_play_media_called = True

    def mark_started(self) -> None:
        if not self.stream_started:
            self.stream_started = True
            self.emit_status("ha_playback_started")

    def finish(self) -> None:
        if not self.terminal:
            self.terminal = True
            self.terminal_at = time.time()
            self.emit_status("ha_playback_finished")

    def fail(self, reason: str) -> None:
        if not self.terminal:
            self.failed = True
            self.terminal = True
            self.terminal_at = time.time()
            self.fail_reason = reason
            self.emit_status("ha_playback_failed", reason=reason)
            self.frame_queue.put(None)

    def cancel(self, reason: str = "cancelled") -> None:
        self.cancelled = True
        self.fail(reason)

    def emit_status(self, event_type: str, **extra: object) -> None:
        payload = {"type": event_type, "session_id": self.session_id}
        payload.update(extra)
        self.status_queue.put(payload)

    def pop_status(self) -> dict | None:
        try:
            return self.status_queue.get_nowait()
        except queue.Empty:
            return None

    def iter_ogg(self) -> Iterator[bytes]:
        self.mark_started()
        muxer = OggOpusMuxer(
            sample_rate=self.sample_rate,
            frame_duration_ms=self.frame_duration_ms,
        )
        try:
            yield from muxer.headers()

            while True:
                try:
                    frame = self.frame_queue.get(timeout=self.timeout_ms / 1000)
                except queue.Empty:
                    self.fail("timeout")
                    yield muxer.end_page()
                    return
                if frame is None:
                    yield muxer.end_page()
                    self.finish()
                    return
                yield muxer.audio_page(frame)
        except GeneratorExit:
            if not self.terminal:
                self.fail("stream_disconnected")
            raise


class PlaybackSessionStore:
    def __init__(self, *, terminal_ttl_seconds: float = 3600) -> None:
        self._sessions: dict[str, PlaybackSession] = {}
        self._active_by_key: dict[tuple[str, str], str] = {}
        self._terminal_ttl_seconds = terminal_ttl_seconds

    def create(
        self,
        request: PlaybackSessionRequest,
        *,
        session_id: str,
        stream_url: str,
        upload_url: str,
    ) -> PlaybackSession:
        self.prune_terminal()
        key = (request.device_id, request.client_id)
        if request.replace_existing:
            old_id = self._active_by_key.get(key)
            if old_id:
                old = self._sessions.get(old_id)
                if old and not old.terminal:
                    old.cancel("superseded")

        session = PlaybackSession(
            session_id=session_id,
            device_id=request.device_id,
            client_id=request.client_id,
            media_player_entity_id=request.media_player_entity_id,
            stream_url=stream_url,
            upload_url=upload_url,
            sample_rate=request.sample_rate,
            frame_duration_ms=request.frame_duration_ms,
            initial_buffer_ms=request.initial_buffer_ms,
            timeout_ms=request.timeout_ms,
        )
        self._sessions[session.session_id] = session
        self._active_by_key[key] = session.session_id
        return session

    def get(self, session_id: str) -> PlaybackSession | None:
        return self._sessions.get(session_id)

    def prune_terminal(self, *, now: float | None = None) -> None:
        current_time = time.time() if now is None else now
        expired_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if session.terminal
            and session.terminal_at is not None
            and current_time - session.terminal_at >= self._terminal_ttl_seconds
        ]
        for session_id in expired_ids:
            session = self._sessions.pop(session_id)
            if self._active_by_key.get(session.key) == session_id:
                self._active_by_key.pop(session.key, None)


def validate_public_stream_base_url(value: str) -> str:
    normalized = value.strip().rstrip("/")
    if not normalized:
        raise ValueError("public stream base URL is required")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("public stream base URL must be an absolute http(s) URL")
    if parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("public stream base URL must be reachable by Home Assistant and the player")
    try:
        ip = socket.gethostbyname(parsed.hostname)
    except OSError:
        ip = ""
    if ip.startswith("127."):
        raise ValueError("public stream base URL must be reachable by Home Assistant and the player")
    return normalized


def call_home_assistant_play_media(
    config: PlaybackConfig,
    entity_id: str,
    stream_url: str,
) -> None:
    if not config.ha_base_url or not config.ha_access_token:
        raise RuntimeError("Home Assistant playback config is incomplete")

    payload = json.dumps(
        {
            "entity_id": entity_id,
            "media_content_id": stream_url,
            "media_content_type": "music",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config.ha_base_url}/api/services/media_player/play_media",
        data=payload,
        headers={
            "Authorization": f"Bearer {config.ha_access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.request_timeout_seconds) as response:
            if response.status >= 300:
                raise RuntimeError(f"Home Assistant play_media failed: {response.status}")
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Home Assistant play_media failed: {exc}") from exc
