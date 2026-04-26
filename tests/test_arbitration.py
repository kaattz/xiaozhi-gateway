from fastapi.testclient import TestClient

from app.main import app


def test_wake_detected_allows_when_no_session_is_active():
    client = TestClient(app)
    client.delete("/active-context")

    response = client.post(
        "/wake-detected",
        json={"device_id": "aa:bb:cc:dd:ee:ff", "wake_word": "你好小智"},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "allow_session"
    assert response.json()["device_id"] == "aa:bb:cc:dd:ee:ff"
    assert response.json()["room_id"] == "living_room"
    assert response.json()["room_name"] == "客厅"
    assert client.get("/active-context").json()["device_id"] == "aa:bb:cc:dd:ee:ff"


def test_wake_detected_denies_when_another_session_is_active():
    client = TestClient(app)
    client.delete("/active-context")
    client.post("/active-context", json={"device_id": "aa:bb:cc:dd:ee:ff"})

    response = client.post(
        "/wake-detected",
        json={"device_id": "11:22:33:44:55:66", "wake_word": "你好小智"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "type": "deny_session",
        "reason": "another_session_active",
        "active_device_id": "aa:bb:cc:dd:ee:ff",
    }
    assert client.get("/active-context").json()["device_id"] == "aa:bb:cc:dd:ee:ff"


def test_wake_detected_allows_same_device_repeat():
    client = TestClient(app)
    client.delete("/active-context")
    client.post("/active-context", json={"device_id": "aa:bb:cc:dd:ee:ff"})

    response = client.post(
        "/wake-detected",
        json={"device_id": "aa:bb:cc:dd:ee:ff", "wake_word": "你好小智"},
    )

    assert response.status_code == 200
    assert response.json()["type"] == "allow_session"
    assert response.json()["device_id"] == "aa:bb:cc:dd:ee:ff"
    assert response.json()["room_id"] == "living_room"


def test_wake_detected_rejects_unknown_device():
    client = TestClient(app)
    client.delete("/active-context")

    response = client.post(
        "/wake-detected",
        json={"device_id": "unknown", "wake_word": "你好小智"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "device not found"}
