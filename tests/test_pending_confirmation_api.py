from fastapi.testclient import TestClient

import app.main as main
from app.main import app
from app.pending_confirmations import PendingConfirmationStore


client = TestClient(app)


def reset_pending_store(monkeypatch, now=lambda: 100.0) -> PendingConfirmationStore:
    store = PendingConfirmationStore(now=now)
    monkeypatch.setattr(main, "pending_confirmations", store)
    return store


def test_create_pending_confirmation_auto_fills_client_id(monkeypatch):
    reset_pending_store(monkeypatch)

    response = client.post(
        "/pending-confirmations",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "living_room",
            "prompt": "现在房间温度比较高，是否打开空调？",
            "ttl_seconds": 30,
            "metadata": {"entity_id": "climate.living_room_ac"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert body["expires_at"] == 130.0
    assert body["client_id"] == ""
    assert body["metadata"] == {"entity_id": "climate.living_room_ac"}
    assert body["confirmation_id"]


def test_get_active_pending_confirmation(monkeypatch):
    reset_pending_store(monkeypatch)
    created = client.post(
        "/pending-confirmations",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "living_room",
            "prompt": "是否打开空调？",
        },
    ).json()

    response = client.get(
        "/pending-confirmations/active?device_id=aa:bb:cc:dd:ee:ff&room_id=living_room"
    )

    assert response.status_code == 200
    assert response.json()["active"] is True
    assert response.json()["confirmation_id"] == created["confirmation_id"]
    assert response.json()["prompt"] == "是否打开空调？"


def test_get_active_pending_confirmation_returns_inactive_when_none(monkeypatch):
    reset_pending_store(monkeypatch)

    response = client.get(
        "/pending-confirmations/active?device_id=aa:bb:cc:dd:ee:ff&room_id=living_room"
    )

    assert response.status_code == 200
    assert response.json() == {
        "active": False,
        "status": "no_pending_confirmation",
    }


def test_get_active_pending_confirmation_returns_expired_status(monkeypatch):
    now = [100.0]
    reset_pending_store(monkeypatch, now=lambda: now[0])
    created = client.post(
        "/pending-confirmations",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "living_room",
            "prompt": "是否打开空调？",
            "ttl_seconds": 5,
        },
    ).json()

    now[0] = 106.0
    response = client.get(
        "/pending-confirmations/active?device_id=aa:bb:cc:dd:ee:ff&room_id=living_room"
    )

    assert response.status_code == 200
    assert response.json() == {
        "active": False,
        "status": "expired",
        "confirmation_id": created["confirmation_id"],
    }


def test_get_active_pending_confirmation_drops_stale_expired_status(monkeypatch):
    now = [100.0]
    reset_pending_store(monkeypatch, now=lambda: now[0])
    client.post(
        "/pending-confirmations",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "living_room",
            "prompt": "是否打开空调？",
            "ttl_seconds": 5,
        },
    )

    now[0] = 226.0
    response = client.get(
        "/pending-confirmations/active?device_id=aa:bb:cc:dd:ee:ff&room_id=living_room"
    )

    assert response.status_code == 200
    assert response.json() == {
        "active": False,
        "status": "no_pending_confirmation",
    }


def test_resolve_pending_confirmation_yes_fires_confirmed_response(monkeypatch):
    reset_pending_store(monkeypatch)
    created = client.post(
        "/pending-confirmations",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "living_room",
            "prompt": "是否打开空调？",
            "metadata": {"automation": "hot_room"},
        },
    ).json()

    response = client.post(
        f"/pending-confirmations/{created['confirmation_id']}/resolve",
        json={
            "decision": "yes",
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "living_room",
            "source": "xiaozhi_mcp",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "confirmation_id": created["confirmation_id"],
        "status": "confirmed",
        "decision": "yes",
        "device_id": "aa:bb:cc:dd:ee:ff",
        "room_id": "living_room",
        "metadata": {"automation": "hot_room"},
    }


def test_pending_confirmation_rejects_unknown_device(monkeypatch):
    reset_pending_store(monkeypatch)

    response = client.post(
        "/pending-confirmations",
        json={
            "device_id": "missing",
            "room_id": "living_room",
            "prompt": "是否打开空调？",
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "device not found"


def test_pending_confirmation_rejects_room_mismatch_on_create(monkeypatch):
    reset_pending_store(monkeypatch)

    response = client.post(
        "/pending-confirmations",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "bedroom",
            "prompt": "是否打开空调？",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "room_mismatch"


def test_pending_confirmation_rejects_duplicate_and_mismatch(monkeypatch):
    reset_pending_store(monkeypatch)
    first = client.post(
        "/pending-confirmations",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "living_room",
            "prompt": "是否打开空调？",
        },
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/pending-confirmations",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "living_room",
            "prompt": "是否打开窗帘？",
        },
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "pending confirmation already exists"

    mismatch = client.post(
        f"/pending-confirmations/{first.json()['confirmation_id']}/resolve",
        json={
            "decision": "yes",
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "bedroom",
            "source": "xiaozhi_mcp",
        },
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"] == "room_mismatch"
