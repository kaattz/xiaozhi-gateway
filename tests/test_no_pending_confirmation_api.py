from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_pending_confirmation_api_is_removed():
    create = client.post(
        "/pending-confirmations",
        json={
            "device_id": "aa:bb:cc:dd:ee:ff",
            "room_id": "living_room",
            "prompt": "是否打开空调？",
        },
    )
    active = client.get(
        "/pending-confirmations/active?device_id=aa:bb:cc:dd:ee:ff&room_id=living_room"
    )

    assert create.status_code == 404
    assert active.status_code == 404
