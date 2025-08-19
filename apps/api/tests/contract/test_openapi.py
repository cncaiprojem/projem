from __future__ import annotations

from starlette.testclient import TestClient

from app.main import app


def test_openapi_ok():
    client = TestClient(app)
    r = client.get("/openapi.json")
    assert r.status_code == 200
    data = r.json()
    assert "paths" in data
