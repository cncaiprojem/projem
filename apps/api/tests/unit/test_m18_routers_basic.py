from fastapi.testclient import TestClient
from app.main import app


def test_fixture_create_and_list_smoke():
    c = TestClient(app)
    r = c.post("/api/v1/fixtures", json={"name": "Vise-100", "type": "vise", "safety_clear_mm": 10})
    assert r.status_code in (200, 201)
    r2 = c.get("/api/v1/fixtures")
    assert r2.status_code == 200
    assert "items" in r2.json()


def test_setup_flow_smoke():
    c = TestClient(app)
    # Proje oluştur
    r = c.post(
        "/api/v1/projects",
        headers={"Idempotency-Key": "t-setup-1"},
        json={"name": "M18Test", "type": "part", "source": "prompt"},
    )
    assert r.status_code == 200
    pid = r.json()["id"]
    # Setup create
    r2 = c.post(
        "/api/v1/setups",
        headers={"Idempotency-Key": "t-setup-2"},
        json={"project_id": pid, "name": "Top", "wcs": "G54"},
    )
    assert r2.status_code in (200, 201)
    sid = r2.json()["id"]
    # Plan ops3d
    r3 = c.post(
        f"/api/v1/setups/{sid}/plan-ops3d",
        json={"ops": [{"op_type": "surface", "params": {"stepover_pct": 30}}]},
    )
    assert r3.status_code == 202
    # List setups
    r4 = c.get(f"/api/v1/setups/project/{pid}")
    assert r4.status_code == 200
    assert "items" in r4.json()
