from fastapi.testclient import TestClient

from app.main import app


def test_session_end_keeps_active_context_for_late_tool_calls():
    client = TestClient(app)
    client.delete("/active-context")
    client.post("/active-context", json={"device_id": "aa:bb:cc:dd:ee:ff"})

    response = client.post(
        "/session/end",
        json={"device_id": "aa:bb:cc:dd:ee:ff"},
    )

    assert response.status_code == 200
    assert response.json() == {"ended": True}
    context = client.get("/active-context").json()
    assert context["active"] is True
    assert context["device_id"] == "aa:bb:cc:dd:ee:ff"


def test_session_end_does_not_clear_another_device_session():
    client = TestClient(app)
    client.delete("/active-context")
    client.post("/active-context", json={"device_id": "aa:bb:cc:dd:ee:ff"})
    client.post("/active-context", json={"device_id": "11:22:33:44:55:66"})

    response = client.post(
        "/session/end",
        json={"device_id": "11:22:33:44:55:66"},
    )

    assert response.status_code == 200
    assert response.json() == {"ended": True}
    response = client.get(
        "/active-context",
        params={"device_id": "aa:bb:cc:dd:ee:ff"},
    )
    assert response.json()["active"] is True
    assert response.json()["device_id"] == "aa:bb:cc:dd:ee:ff"


def test_session_end_is_idempotent_when_no_session_is_active():
    client = TestClient(app)
    client.delete("/active-context")

    response = client.post(
        "/session/end",
        json={"device_id": "aa:bb:cc:dd:ee:ff"},
    )

    assert response.status_code == 200
    assert response.json() == {"ended": False}
