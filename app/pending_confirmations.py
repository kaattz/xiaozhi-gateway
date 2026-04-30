import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any


class PendingConfirmationError(RuntimeError):
    pass


class PendingConflictError(PendingConfirmationError):
    pass


class PendingNotFoundError(PendingConfirmationError):
    pass


class PendingMismatchError(PendingConfirmationError):
    pass


class PendingResolvedError(PendingConfirmationError):
    pass


@dataclass(frozen=True)
class PendingConfirmation:
    confirmation_id: str
    device_id: str
    client_id: str
    room_id: str
    prompt: str
    status: str
    expires_at: float
    metadata: dict[str, Any] = field(default_factory=dict)
    decision: str | None = None


class PendingConfirmationStore:
    def __init__(
        self,
        now: Callable[[], float] = time.time,
        terminal_retention_seconds: int = 120,
    ) -> None:
        self._now = now
        self._terminal_retention_seconds = terminal_retention_seconds
        self._items: dict[str, PendingConfirmation] = {}
        self._lock = threading.RLock()

    def create(
        self,
        *,
        device_id: str,
        client_id: str,
        room_id: str,
        prompt: str,
        ttl_seconds: int,
        metadata: dict[str, Any] | None = None,
    ) -> PendingConfirmation:
        with self._lock:
            self._mark_expired()
            if self.get_active(device_id=device_id, room_id=None) is not None:
                raise PendingConflictError("pending confirmation already exists")

            item = PendingConfirmation(
                confirmation_id=uuid.uuid4().hex,
                device_id=device_id,
                client_id=client_id,
                room_id=room_id,
                prompt=prompt,
                status="pending",
                expires_at=self._now() + ttl_seconds,
                metadata=dict(metadata or {}),
            )
            self._items[item.confirmation_id] = item
            return item

    def get_active(
        self,
        *,
        device_id: str | None = None,
        room_id: str | None = None,
    ) -> PendingConfirmation | None:
        with self._lock:
            self._mark_expired()
            for item in self._items.values():
                if item.status != "pending":
                    continue
                if device_id is not None and item.device_id != device_id:
                    continue
                if room_id is not None and item.room_id != room_id:
                    continue
                return item
            return None

    def get_latest(
        self,
        *,
        device_id: str | None = None,
        room_id: str | None = None,
    ) -> PendingConfirmation | None:
        with self._lock:
            self._mark_expired()
            for item in reversed(list(self._items.values())):
                if device_id is not None and item.device_id != device_id:
                    continue
                if room_id is not None and item.room_id != room_id:
                    continue
                return item
            return None

    def resolve(
        self,
        confirmation_id: str,
        *,
        decision: str,
        device_id: str,
        room_id: str,
    ) -> PendingConfirmation:
        with self._lock:
            self._mark_expired()
            item = self._items.get(confirmation_id)
            if item is None:
                raise PendingNotFoundError("no_pending_confirmation")
            if item.device_id != device_id:
                raise PendingMismatchError("device_mismatch")
            if item.room_id != room_id:
                raise PendingMismatchError("room_mismatch")
            if item.status == "expired":
                raise PendingResolvedError("expired")
            if item.status != "pending":
                raise PendingResolvedError("already_resolved")
            if decision not in {"yes", "no"}:
                raise ValueError(f"unsupported decision: {decision}")

            updated = replace(
                item,
                status="confirmed" if decision == "yes" else "rejected",
                decision=decision,
            )
            self._items[confirmation_id] = updated
            return updated

    def _mark_expired(self) -> None:
        now = self._now()
        for confirmation_id, item in list(self._items.items()):
            if item.status == "pending" and item.expires_at <= now:
                self._items[confirmation_id] = replace(item, status="expired")
        for confirmation_id, item in list(self._items.items()):
            if item.status != "pending" and item.expires_at + self._terminal_retention_seconds <= now:
                del self._items[confirmation_id]
