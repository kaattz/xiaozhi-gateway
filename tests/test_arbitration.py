from fastapi.testclient import TestClient
import threading
import time

from app.main import app


def test_wake_detected_allows_when_no_session_is_active():
    client = TestClient(app)
    client.delete("/active-context")

    response = client.post(
        "/wake-detected",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "wake_word": "你好小智",
            "wake_rms_dbfs": -18.0,
        },
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
        json={
            "device_id": "11:22:33:44:55:66",
            "wake_word": "你好小智",
            "wake_rms_dbfs": -16.0,
        },
    )

    assert response.status_code == 200
    assert response.json()["type"] == "allow_session"
    assert client.get("/active-context").json() == {
        "active": False,
        "status": "multiple_active_contexts",
    }


def test_wake_detected_allows_same_device_repeat():
    client = TestClient(app)
    client.delete("/active-context")
    client.post("/active-context", json={"device_id": "aa:bb:cc:dd:ee:ff"})

    response = client.post(
        "/wake-detected",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "wake_word": "你好小智",
            "wake_rms_dbfs": -18.0,
        },
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
        json={
            "device_id": "unknown",
            "wake_word": "你好小智",
            "wake_rms_dbfs": -18.0,
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "device not found"}


def test_wake_detected_requires_wake_rms_dbfs():
    client = TestClient(app)
    client.delete("/active-context")

    response = client.post(
        "/wake-detected",
        json={"device_id": "aa:bb:cc:dd:ee:ff", "wake_word": "你好小智"},
    )

    assert response.status_code == 422


def test_same_group_prefers_higher_adjusted_wake_rms(tmp_path):
    from app.arbitration import WakeArbitrationStore, decide_wake
    from app.models import DeviceMapping, WakeDetectedRequest
    from app.session_store import SessionStore

    devices = [
        DeviceMapping(
            key="living",
            device_id="living-device",
            room_id="living_room",
            room_name="客厅",
            ha_area_id="living_room",
            wake_group="public_area",
            priority=10,
        ),
        DeviceMapping(
            key="dining",
            device_id="dining-device",
            room_id="dining_room",
            room_name="餐厅",
            ha_area_id="dining_room",
            wake_group="public_area",
            priority=10,
        ),
    ]
    store = SessionStore(state_path=tmp_path / "state.json")
    arbitration = WakeArbitrationStore(window_ms=50)
    results = {}

    def call(name, request):
        results[name] = decide_wake(
            devices,
            store,
            request,
            arbitration_store=arbitration,
        )

    low_thread = threading.Thread(
        target=call,
        args=(
            "low",
            WakeDetectedRequest(
                device_id="living-device",
                wake_word="你好小智",
                wake_rms_dbfs=-30.0,
            ),
        ),
    )
    high_thread = threading.Thread(
        target=call,
        args=(
            "high",
            WakeDetectedRequest(
                device_id="dining-device",
                wake_word="你好小智",
                wake_rms_dbfs=-15.0,
            ),
        ),
    )

    low_thread.start()
    time.sleep(0.01)
    high_thread.start()
    low_thread.join(1)
    high_thread.join(1)

    low = results["low"]
    high = results["high"]
    assert high["type"] == "allow_session"
    assert low == {
        "type": "deny_session",
        "reason": "lower_wake_rms",
        "winner_device_id": "dining-device",
    }


def test_same_group_uses_priority_when_wake_rms_is_close(tmp_path):
    from app.arbitration import WakeArbitrationStore, decide_wake
    from app.models import DeviceMapping, WakeDetectedRequest
    from app.session_store import SessionStore

    devices = [
        DeviceMapping(
            key="living",
            device_id="living-device",
            room_id="living_room",
            room_name="客厅",
            ha_area_id="living_room",
            wake_group="public_area",
            priority=100,
        ),
        DeviceMapping(
            key="dining",
            device_id="dining-device",
            room_id="dining_room",
            room_name="餐厅",
            ha_area_id="dining_room",
            wake_group="public_area",
            priority=10,
        ),
    ]
    store = SessionStore(state_path=tmp_path / "state.json")
    arbitration = WakeArbitrationStore(window_ms=50, close_rms_threshold_db=3.0)
    results = {}

    def call(name, request):
        results[name] = decide_wake(
            devices,
            store,
            request,
            arbitration_store=arbitration,
        )

    winner_thread = threading.Thread(
        target=call,
        args=(
            "winner",
            WakeDetectedRequest(
                device_id="living-device",
                wake_word="你好小智",
                wake_rms_dbfs=-21.0,
            ),
        ),
    )
    loser_thread = threading.Thread(
        target=call,
        args=(
            "loser",
            WakeDetectedRequest(
                device_id="dining-device",
                wake_word="你好小智",
                wake_rms_dbfs=-20.0,
            ),
        ),
    )

    winner_thread.start()
    time.sleep(0.01)
    loser_thread.start()
    winner_thread.join(1)
    loser_thread.join(1)

    winner = results["winner"]
    loser = results["loser"]
    assert winner["type"] == "allow_session"
    assert loser["type"] == "deny_session"
    assert loser["reason"] == "lower_priority"


def test_single_device_group_allows_without_wait(tmp_path):
    from app.arbitration import WakeArbitrationStore, decide_wake
    from app.models import DeviceMapping, WakeDetectedRequest
    from app.session_store import SessionStore

    devices = [
        DeviceMapping(
            key="bedroom",
            device_id="bedroom-device",
            room_id="bedroom",
            room_name="卧室",
            ha_area_id="bedroom",
            wake_group="bedroom",
            priority=0,
        )
    ]
    store = SessionStore(state_path=tmp_path / "state.json")
    arbitration = WakeArbitrationStore(window_ms=500)

    decision = decide_wake(
        devices,
        store,
        WakeDetectedRequest(
            device_id="bedroom-device",
            wake_word="你好小智",
            wake_rms_dbfs=-18.0,
        ),
        arbitration_store=arbitration,
    )

    assert decision["type"] == "allow_session"
