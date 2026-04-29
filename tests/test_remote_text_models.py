import pytest
from pydantic import ValidationError

from app.models import RemoteTextJobRequest


def test_remote_text_rejects_empty_text():
    with pytest.raises(ValidationError):
        RemoteTextJobRequest(device_id="aa:bb:cc:dd:ee:ff", text="")


def test_remote_text_rejects_overlong_text():
    with pytest.raises(ValidationError):
        RemoteTextJobRequest(device_id="aa:bb:cc:dd:ee:ff", text="x" * 121)


def test_remote_text_accepts_valid_text():
    request = RemoteTextJobRequest(
        device_id="aa:bb:cc:dd:ee:ff",
        client_id="livingroom_xiaozhi",
        text="打开客厅灯",
    )

    assert request.text == "打开客厅灯"
