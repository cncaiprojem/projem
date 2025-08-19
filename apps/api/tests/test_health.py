from fastapi.testclient import TestClient

from app.main import app


def test_healthz():
    client = TestClient(app)
    resp = client.get("/api/v1/healthz")
    assert resp.status_code in (200, 503)
    data = resp.json()
    assert "status" in data and "dependencies" in data
