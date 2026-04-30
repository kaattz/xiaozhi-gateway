from ctypes.util import find_library

import pytest

from app.audio_frames import (
    encode_raw_opus_frames,
)


def test_encode_raw_opus_frames_encodes_one_60ms_packet_for_960_samples():
    if find_library("opus") is None:
        pytest.skip("system libopus is not installed")

    pcm = b"\x00\x00" * 960

    frames = encode_raw_opus_frames(pcm)

    assert len(frames) == 1
    assert frames[0]
