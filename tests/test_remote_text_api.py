from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_remote_text_api_is_not_registered():
    paths = app.openapi()["paths"]

    assert "/remote-text/jobs" not in paths
    assert "/remote-text/jobs/{job_id}/frames" not in paths
