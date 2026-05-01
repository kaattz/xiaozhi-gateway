from fastapi.testclient import TestClient

from app.main import app
from app.models import DeviceMapping
from app.session_store import SessionStore


def test_active_context_is_empty_by_default():
    client = TestClient(app)
    client.delete("/active-context")

    response = client.get("/active-context")

    assert response.status_code == 200
    assert response.json() == {"active": False}


def test_active_context_can_be_set_from_device_id():
    client = TestClient(app)
    client.delete("/active-context")

    response = client.post(
        "/active-context",
        json={"device_id": "aa:bb:cc:dd:ee:ff"},
    )

    assert response.status_code == 200
    assert response.json()["active"] is True
    assert response.json()["device_id"] == "aa:bb:cc:dd:ee:ff"
    assert response.json()["room_id"] == "living_room"
    assert response.json()["room_name"] == "客厅"
    assert response.json()["ha_area_id"] == "living_room"


def test_active_context_can_be_cleared():
    client = TestClient(app)
    client.post("/active-context", json={"device_id": "aa:bb:cc:dd:ee:ff"})

    response = client.delete("/active-context")

    assert response.status_code == 200
    assert response.json() == {"active": False}
    assert client.get("/active-context").json() == {"active": False}


def test_active_context_reports_ambiguous_when_multiple_sessions_exist():
    client = TestClient(app)
    client.delete("/active-context")
    client.post("/active-context", json={"device_id": "aa:bb:cc:dd:ee:ff"})
    client.post("/active-context", json={"device_id": "11:22:33:44:55:66"})

    response = client.get("/active-context")

    assert response.status_code == 200
    assert response.json() == {
        "active": False,
        "status": "multiple_active_contexts",
    }


def test_active_context_can_be_queried_by_device_id():
    client = TestClient(app)
    client.delete("/active-context")
    client.post("/active-context", json={"device_id": "aa:bb:cc:dd:ee:ff"})
    client.post("/active-context", json={"device_id": "11:22:33:44:55:66"})

    response = client.get(
        "/active-context",
        params={"device_id": "aa:bb:cc:dd:ee:ff"},
    )

    assert response.status_code == 200
    assert response.json()["active"] is True
    assert response.json()["device_id"] == "aa:bb:cc:dd:ee:ff"


def test_session_store_persists_active_context(tmp_path):
    state_path = tmp_path / "state.json"
    device = DeviceMapping(
        key="living_room_xiaozhi",
        device_id="aa:bb:cc:dd:ee:ff",
        room_id="living_room",
        room_name="Living Room",
        ha_area_id="living_room",
    )

    first = SessionStore(state_path=state_path, ttl_seconds=120)
    first.set(device)
    second = SessionStore(state_path=state_path, ttl_seconds=120)

    context = second.get()

    assert context is not None
    assert context.device_id == "aa:bb:cc:dd:ee:ff"
    assert context.room_id == "living_room"


def test_session_store_returns_multiple_active_contexts(tmp_path):
    state_path = tmp_path / "state.json"
    first = DeviceMapping(
        key="living_room_xiaozhi",
        device_id="aa:bb:cc:dd:ee:ff",
        room_id="living_room",
        room_name="Living Room",
        ha_area_id="living_room",
    )
    second = DeviceMapping(
        key="bedroom_xiaozhi",
        device_id="11:22:33:44:55:66",
        room_id="bedroom",
        room_name="Bedroom",
        ha_area_id="bedroom",
    )
    store = SessionStore(state_path=state_path, ttl_seconds=120)
    store.set(first)
    store.set(second)

    assert store.get() == "multiple_active_contexts"
    assert store.get("aa:bb:cc:dd:ee:ff").device_id == "aa:bb:cc:dd:ee:ff"


def test_session_store_expires_active_context(tmp_path):
    now = 1000.0
    state_path = tmp_path / "state.json"
    device = DeviceMapping(
        key="living_room_xiaozhi",
        device_id="aa:bb:cc:dd:ee:ff",
        room_id="living_room",
        room_name="Living Room",
        ha_area_id="living_room",
    )
    store = SessionStore(
        state_path=state_path,
        ttl_seconds=10,
        now=lambda: now,
    )
    store.set(device)

    expired = SessionStore(
        state_path=state_path,
        ttl_seconds=10,
        now=lambda: now + 11,
    )

    assert expired.get() is None
