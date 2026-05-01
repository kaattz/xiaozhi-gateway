import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.models import ActiveContext, DeviceMapping, WakeDetectedRequest
from app.session_store import SessionStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WakeCandidate:
    device: DeviceMapping
    wake_rms_dbfs: float

    @property
    def adjusted_wake_rms_dbfs(self) -> float:
        return self.wake_rms_dbfs + self.device.mic_gain_offset_db


@dataclass
class WakeArbitrationRound:
    group: str
    expected_device_ids: set[str]
    deadline: float
    candidates: dict[str, WakeCandidate] = field(default_factory=dict)
    result: dict[str, dict] | None = None
    finalized_at: float | None = None


class WakeArbitrationStore:
    def __init__(
        self,
        window_ms: int = 300,
        close_rms_threshold_db: float = 3.0,
        result_ttl_seconds: float = 1.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        if window_ms <= 0:
            raise ValueError("window_ms must be positive")
        if close_rms_threshold_db < 0:
            raise ValueError("close_rms_threshold_db must be non-negative")

        self._window_seconds = window_ms / 1000
        self._close_rms_threshold_db = close_rms_threshold_db
        self._result_ttl_seconds = result_ttl_seconds
        self._now = now
        self._condition = threading.Condition()
        self._rounds: dict[str, WakeArbitrationRound] = {}

    def decide(
        self,
        group_devices: list[DeviceMapping],
        candidate: WakeCandidate,
    ) -> dict:
        group = candidate.device.wake_group
        expected_device_ids = {device.device_id for device in group_devices}

        with self._condition:
            self._cleanup_locked()
            current = self._rounds.get(group)
            now = self._now()

            if current is None:
                current = WakeArbitrationRound(
                    group=group,
                    expected_device_ids=expected_device_ids,
                    deadline=now + self._window_seconds,
                )
                self._rounds[group] = current
            elif current.result is not None:
                if candidate.device.device_id in current.result:
                    return current.result[candidate.device.device_id]
                return _deny_response(
                    "arbitration_window_closed",
                    current.result["winner"]["device_id"],
                )

            current.candidates[candidate.device.device_id] = candidate
            if current.expected_device_ids.issubset(current.candidates):
                self._finalize_locked(current)
                self._condition.notify_all()
                return current.result[candidate.device.device_id]

            while current.result is None:
                remaining = current.deadline - self._now()
                if remaining <= 0:
                    self._finalize_locked(current)
                    self._condition.notify_all()
                    break
                self._condition.wait(timeout=remaining)

            return current.result[candidate.device.device_id]

    def _cleanup_locked(self) -> None:
        now = self._now()
        expired_groups: list[str] = []
        for group, round_ in self._rounds.items():
            if round_.result is None and round_.deadline <= now:
                self._finalize_locked(round_)
            if (
                round_.finalized_at is not None
                and round_.finalized_at + self._result_ttl_seconds <= now
            ):
                expired_groups.append(group)

        for group in expired_groups:
            del self._rounds[group]

    def _finalize_locked(self, round_: WakeArbitrationRound) -> None:
        if round_.result is not None:
            return

        candidates = list(round_.candidates.values())
        if not candidates:
            raise RuntimeError("wake arbitration round has no candidates")

        winner = _pick_winner(candidates, self._close_rms_threshold_db)
        result: dict[str, dict] = {
            "winner": {
                "type": "allow_session",
                "device_id": winner.device.device_id,
            }
        }
        for candidate in candidates:
            device_id = candidate.device.device_id
            if device_id == winner.device.device_id:
                result[device_id] = {"type": "allow_session"}
            else:
                result[device_id] = _deny_response(
                    _loser_reason(winner, candidate, self._close_rms_threshold_db),
                    winner.device.device_id,
                )

        round_.result = result
        round_.finalized_at = self._now()
        loser_device_ids = [
            candidate.device.device_id
            for candidate in candidates
            if candidate.device.device_id != winner.device.device_id
        ]
        candidate_details = [
            {
                "device_id": candidate.device.device_id,
                "wake_rms_dbfs": candidate.wake_rms_dbfs,
                "adjusted_wake_rms_dbfs": candidate.adjusted_wake_rms_dbfs,
                "priority": candidate.device.priority,
                "result": "winner"
                if candidate.device.device_id == winner.device.device_id
                else "loser",
                "reason": ""
                if candidate.device.device_id == winner.device.device_id
                else result[candidate.device.device_id]["reason"],
            }
            for candidate in candidates
        ]
        logger.info(
            "wake arbitration finalized wake_group=%s winner_device_id=%s "
            "loser_device_ids=%s candidate_details=%s",
            round_.group,
            winner.device.device_id,
            loser_device_ids,
            candidate_details,
        )


def find_wake_device(
    devices: list[DeviceMapping], request: WakeDetectedRequest
) -> DeviceMapping | None:
    for device in devices:
        if device.device_id == request.device_id:
            return device

    return None


def decide_wake(
    devices: list[DeviceMapping],
    session_store: SessionStore,
    request: WakeDetectedRequest,
    arbitration_store: WakeArbitrationStore | None = None,
) -> dict:
    device = find_wake_device(devices, request)
    if device is None:
        return {"type": "unknown_device"}

    group_devices = [
        configured_device
        for configured_device in devices
        if configured_device.wake_group == device.wake_group
    ]
    if len(group_devices) <= 1:
        context = session_store.set(device)
        logger.info(
            "wake allowed without arbitration device_id=%s group=%s wake_rms_dbfs=%.2f",
            device.device_id,
            device.wake_group,
            request.wake_rms_dbfs,
        )
        return _allow_response(context)

    if arbitration_store is None:
        arbitration_store = WakeArbitrationStore()

    decision = arbitration_store.decide(
        group_devices,
        WakeCandidate(device=device, wake_rms_dbfs=request.wake_rms_dbfs),
    )
    if decision["type"] == "allow_session":
        context = session_store.set(device)
        logger.info(
            "wake allowed device_id=%s group=%s wake_rms_dbfs=%.2f adjusted=%.2f",
            device.device_id,
            device.wake_group,
            request.wake_rms_dbfs,
            request.wake_rms_dbfs + device.mic_gain_offset_db,
        )
        return _allow_response(context)

    logger.info(
        "wake denied device_id=%s group=%s reason=%s winner_device_id=%s",
        device.device_id,
        device.wake_group,
        decision["reason"],
        decision["winner_device_id"],
    )
    return decision


def _pick_winner(
    candidates: list[WakeCandidate],
    close_rms_threshold_db: float,
) -> WakeCandidate:
    by_rms = sorted(
        candidates,
        key=lambda candidate: (
            -candidate.adjusted_wake_rms_dbfs,
            -candidate.device.priority,
            candidate.device.device_id,
        ),
    )
    if len(by_rms) == 1:
        return by_rms[0]

    rms_gap = by_rms[0].adjusted_wake_rms_dbfs - by_rms[1].adjusted_wake_rms_dbfs
    if rms_gap >= close_rms_threshold_db:
        return by_rms[0]

    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.device.priority,
            -candidate.adjusted_wake_rms_dbfs,
            candidate.device.device_id,
        ),
    )[0]


def _loser_reason(
    winner: WakeCandidate,
    loser: WakeCandidate,
    close_rms_threshold_db: float,
) -> str:
    rms_gap = winner.adjusted_wake_rms_dbfs - loser.adjusted_wake_rms_dbfs
    if rms_gap >= close_rms_threshold_db:
        return "lower_wake_rms"
    if winner.device.priority > loser.device.priority:
        return "lower_priority"
    return "lower_wake_rms"


def _deny_response(reason: str, winner_device_id: str) -> dict:
    return {
        "type": "deny_session",
        "reason": reason,
        "winner_device_id": winner_device_id,
    }


def _allow_response(context: ActiveContext) -> dict:
    return {
        "type": "allow_session",
        **context.model_dump(),
    }
