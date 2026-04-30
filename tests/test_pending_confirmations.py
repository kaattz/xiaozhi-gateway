import pytest
from pathlib import Path

from app.pending_confirmations import (
    PendingConfirmationStore,
    PendingConflictError,
    PendingMismatchError,
    PendingNotFoundError,
    PendingResolvedError,
)


ROOT = Path(__file__).resolve().parents[1]


def test_pending_confirmation_create_and_get_active():
    now = [100.0]
    store = PendingConfirmationStore(now=lambda: now[0])

    pending = store.create(
        device_id="aa:bb:cc:dd:ee:ff",
        client_id="livingroom_xiaozhi",
        room_id="living_room",
        prompt="是否打开空调？",
        ttl_seconds=30,
        metadata={"entity_id": "climate.living_room_ac"},
    )

    assert pending.status == "pending"
    assert pending.expires_at == 130.0
    active = store.get_active(device_id="aa:bb:cc:dd:ee:ff", room_id="living_room")
    assert active == pending


def test_pending_confirmation_rejects_duplicate_device_pending():
    store = PendingConfirmationStore(now=lambda: 100.0)
    store.create(
        device_id="aa",
        client_id="client",
        room_id="living_room",
        prompt="是否打开空调？",
        ttl_seconds=30,
    )

    with pytest.raises(PendingConflictError, match="pending confirmation already exists"):
        store.create(
            device_id="aa",
            client_id="client",
            room_id="living_room",
            prompt="是否打开窗帘？",
            ttl_seconds=30,
        )


def test_pending_confirmation_resolves_yes_and_no():
    store = PendingConfirmationStore(now=lambda: 100.0)
    first = store.create(
        device_id="aa",
        client_id="client",
        room_id="living_room",
        prompt="是否打开空调？",
        ttl_seconds=30,
    )
    confirmed = store.resolve(
        first.confirmation_id,
        decision="yes",
        device_id="aa",
        room_id="living_room",
    )
    assert confirmed.status == "confirmed"
    assert confirmed.decision == "yes"

    second = store.create(
        device_id="aa",
        client_id="client",
        room_id="living_room",
        prompt="是否打开窗帘？",
        ttl_seconds=30,
    )
    rejected = store.resolve(
        second.confirmation_id,
        decision="no",
        device_id="aa",
        room_id="living_room",
    )
    assert rejected.status == "rejected"
    assert rejected.decision == "no"


def test_pending_confirmation_expired_items_are_not_active_or_resolvable():
    now = [100.0]
    store = PendingConfirmationStore(now=lambda: now[0])
    pending = store.create(
        device_id="aa",
        client_id="client",
        room_id="living_room",
        prompt="是否打开空调？",
        ttl_seconds=5,
    )

    now[0] = 106.0

    assert store.get_active(device_id="aa", room_id="living_room") is None
    with pytest.raises(PendingResolvedError, match="expired"):
        store.resolve(
            pending.confirmation_id,
            decision="yes",
            device_id="aa",
            room_id="living_room",
        )


def test_pending_confirmation_resolve_validates_device_and_room():
    store = PendingConfirmationStore(now=lambda: 100.0)
    pending = store.create(
        device_id="aa",
        client_id="client",
        room_id="living_room",
        prompt="是否打开空调？",
        ttl_seconds=30,
    )

    with pytest.raises(PendingMismatchError, match="device_mismatch"):
        store.resolve(
            pending.confirmation_id,
            decision="yes",
            device_id="bb",
            room_id="living_room",
        )
    with pytest.raises(PendingMismatchError, match="room_mismatch"):
        store.resolve(
            pending.confirmation_id,
            decision="yes",
            device_id="aa",
            room_id="bedroom",
        )


def test_pending_confirmation_rejects_unknown_and_repeated_resolve():
    store = PendingConfirmationStore(now=lambda: 100.0)

    with pytest.raises(PendingNotFoundError, match="no_pending_confirmation"):
        store.resolve(
            "missing",
            decision="yes",
            device_id="aa",
            room_id="living_room",
        )

    pending = store.create(
        device_id="aa",
        client_id="client",
        room_id="living_room",
        prompt="是否打开空调？",
        ttl_seconds=30,
    )
    store.resolve(
        pending.confirmation_id,
        decision="yes",
        device_id="aa",
        room_id="living_room",
    )

    with pytest.raises(PendingResolvedError, match="already_resolved"):
        store.resolve(
            pending.confirmation_id,
            decision="yes",
            device_id="aa",
            room_id="living_room",
        )


def test_pending_confirmation_store_serializes_access():
    source = (ROOT / "app" / "pending_confirmations.py").read_text(encoding="utf-8")

    assert "threading.RLock" in source
    assert "self._lock" in source
    assert source.count("with self._lock") >= 4
