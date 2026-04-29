import json
import socket
import subprocess
import wave
from io import BytesIO

from app.config import RemoteTextConfig


SAMPLE_RATE = 16000
FRAME_DURATION_MS = 60
CHANNELS = 1
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_DURATION_MS // 1000
BYTES_PER_SAMPLE = 2
WYOMING_TIMEOUT_SECONDS = 10


def synthesize_remote_text_wav(text: str, config: RemoteTextConfig) -> bytes:
    if config.provider == "wyoming":
        return synthesize_wav_from_wyoming(
            text,
            config.wyoming_host,
            config.wyoming_port,
        )
    raise RuntimeError(f"unsupported remote text provider: {config.provider}")


def synthesize_wav_from_wyoming(
    text: str,
    host: str,
    port: int,
) -> bytes:
    request = json.dumps(
        {
            "type": "synthesize",
            "data": {"text": text},
        },
        separators=(",", ":"),
    ).encode("utf-8") + b"\n"

    with socket.create_connection((host, port), timeout=WYOMING_TIMEOUT_SECONDS) as conn:
        conn.settimeout(WYOMING_TIMEOUT_SECONDS)
        conn.sendall(request)
        reader = conn.makefile("rb")

        sample_rate = 0
        sample_width = 0
        channels = 0
        pcm = bytearray()

        while True:
            header_line = reader.readline()
            if not header_line:
                raise RuntimeError("wyoming piper connection closed before audio-stop")

            event = json.loads(header_line.decode("utf-8"))
            data_length = int(event.get("data_length") or 0)
            if data_length:
                event["data"] = {
                    **(event.get("data") or {}),
                    **json.loads(reader.read(data_length).decode("utf-8")),
                }

            payload_length = int(event.get("payload_length") or 0)
            payload = reader.read(payload_length) if payload_length else b""

            event_type = event.get("type")
            data = event.get("data") or {}
            if event_type == "audio-start":
                sample_rate = int(data["rate"])
                sample_width = int(data["width"])
                channels = int(data["channels"])
            elif event_type == "audio-chunk":
                sample_rate = int(data.get("rate") or sample_rate)
                sample_width = int(data.get("width") or sample_width)
                channels = int(data.get("channels") or channels)
                pcm.extend(payload)
            elif event_type == "audio-stop":
                break

        if not pcm or sample_rate <= 0 or sample_width <= 0 or channels <= 0:
            raise RuntimeError("wyoming piper produced no audio")

        output = BytesIO()
        with wave.open(output, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(bytes(pcm))
        return output.getvalue()


def normalize_wav_to_pcm_s16le(
    wav: bytes,
    ffmpeg_binary: str,
) -> bytes:
    completed = subprocess.run(
        [
            ffmpeg_binary,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "wav",
            "-i",
            "pipe:0",
            "-ac",
            str(CHANNELS),
            "-ar",
            str(SAMPLE_RATE),
            "-f",
            "s16le",
            "pipe:1",
        ],
        input=wav,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        error = completed.stderr.decode(errors="ignore").strip()
        raise RuntimeError(f"audio normalization failed: {error}")
    return completed.stdout


def encode_raw_opus_frames(pcm: bytes) -> list[bytes]:
    import opuslib

    bytes_per_frame = SAMPLES_PER_FRAME * CHANNELS * BYTES_PER_SAMPLE
    if len(pcm) < bytes_per_frame:
        pcm = pcm + b"\x00" * (bytes_per_frame - len(pcm))

    encoder = opuslib.Encoder(SAMPLE_RATE, CHANNELS, opuslib.APPLICATION_VOIP)
    frames: list[bytes] = []
    for offset in range(0, len(pcm), bytes_per_frame):
        chunk = pcm[offset : offset + bytes_per_frame]
        if len(chunk) < bytes_per_frame:
            chunk += b"\x00" * (bytes_per_frame - len(chunk))
        frames.append(encoder.encode(chunk, SAMPLES_PER_FRAME))
    return frames
