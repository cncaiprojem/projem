from fastapi.testclient import TestClient
from app.main import app


def test_fixture_create_list():
    c = TestClient(app)
    r = c.post("/api/v1/fixtures", json={"name": "Vise-200", "type": "vise", "safety_clear_mm": 12})
    assert r.status_code in (200, 201)
    r2 = c.get("/api/v1/fixtures")
    assert r2.status_code == 200
    assert "items" in r2.json()
