SAMPLE_RATE = 16000
FRAME_DURATION_MS = 60
CHANNELS = 1
SAMPLES_PER_FRAME = SAMPLE_RATE * FRAME_DURATION_MS // 1000
BYTES_PER_SAMPLE = 2


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
