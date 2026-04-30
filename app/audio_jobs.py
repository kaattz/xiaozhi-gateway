import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class AudioJob:
    job_id: str
    device_id: str
    frames: list[bytes]
    sample_rate: int
    frame_duration_ms: int
    expires_at: float


class AudioJobStore:
    def __init__(
        self,
        ttl_seconds: int = 120,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._now = now
        self._jobs: dict[str, AudioJob] = {}

    def create(
        self,
        device_id: str,
        frames: list[bytes],
        sample_rate: int,
        frame_duration_ms: int,
    ) -> AudioJob:
        self._cleanup()
        job = AudioJob(
            job_id=uuid.uuid4().hex,
            device_id=device_id,
            frames=frames,
            sample_rate=sample_rate,
            frame_duration_ms=frame_duration_ms,
            expires_at=self._now() + self._ttl_seconds,
        )
        self._jobs[job.job_id] = job
        return job

    def get(self, job_id: str) -> AudioJob | None:
        self._cleanup()
        return self._jobs.get(job_id)

    def delete(self, job_id: str) -> bool:
        return self._jobs.pop(job_id, None) is not None

    def _cleanup(self) -> None:
        now = self._now()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.expires_at <= now
        ]
        for job_id in expired:
            del self._jobs[job_id]
