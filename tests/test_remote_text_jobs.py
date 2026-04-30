from app.audio_jobs import AudioJobStore


def test_job_store_creates_and_reads_frames():
    now = 1000.0
    store = AudioJobStore(now=lambda: now)

    job = store.create(
        device_id="aa:bb:cc:dd:ee:ff",
        frames=[b"one", b"two"],
        sample_rate=16000,
        frame_duration_ms=60,
    )

    stored = store.get(job.job_id)
    assert stored is not None
    assert stored.frames == [b"one", b"two"]
    assert stored.expires_at == 1120.0


def test_job_store_expires_jobs():
    current = 1000.0
    store = AudioJobStore(now=lambda: current)
    job = store.create("device", [b"one"], 16000, 60)

    current = 1121.0

    assert store.get(job.job_id) is None
