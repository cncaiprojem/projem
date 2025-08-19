from fastapi.testclient import TestClient
from app.main import app
from app.services.job_control import queue_pause, queue_resume


def _mk_project(client: TestClient) -> int:
    r = client.post(
        "/api/v1/projects",
        headers={"Idempotency-Key": "t-proj-x"},
        json={"name": "R", "type": "part", "source": "prompt"},
    )
    return r.json()["id"]


def test_plan_ops3d_and_list():
    c = TestClient(app)
    pid = _mk_project(c)
    r2 = c.post(
        "/api/v1/setups",
        headers={"Idempotency-Key": "t-setup-x"},
        json={"project_id": pid, "name": "Top", "wcs": "G54"},
    )
    sid = r2.json()["id"]
    r3 = c.post(
        f"/api/v1/setups/{sid}/plan-ops3d",
        json={"ops": [{"op_type": "surface", "params": {"stepover_pct": 30}}]},
    )
    assert r3.status_code == 202
    r4 = c.get(f"/api/v1/setups/project/{pid}")
    assert r4.status_code == 200
    assert "items" in r4.json()


def test_queue_paused_returns_409():
    c = TestClient(app)
    pid = _mk_project(c)
    r2 = c.post(
        "/api/v1/setups",
        headers={"Idempotency-Key": "t-setup-y"},
        json={"project_id": pid, "name": "Top", "wcs": "G54"},
    )
    sid = r2.json()["id"]
    queue_pause("freecad")
    try:
        r = c.post(f"/api/v1/setups/{sid}/cam")
        assert r.status_code == 409
    finally:
        queue_resume("freecad")
