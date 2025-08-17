# LEGACY TEST FILE - DISABLED
# This test file references legacy models not in Task Master ERD
# The project/setup system has been replaced with Task Master models
"""
from fastapi.testclient import TestClient
from app.main import app


def test_cam_enqueue_broker_down(monkeypatch):
    c = TestClient(app)
    # create project and setup
    p = c.post("/api/v1/projects", headers={"Idempotency-Key": "t-cam-1"}, json={"name": "P", "type": "part", "source": "prompt"}).json()
    s = c.post("/api/v1/setups", headers={"Idempotency-Key": "t-cam-2"}, json={"project_id": p["id"], "name": "Top", "wcs": "G54"}).json()

    def fake_delay(_):
        raise RuntimeError("broker down")

    from app.routers import setups as setups_router
    monkeypatch.setattr(setups_router.setup_cam_task, "delay", fake_delay)
    r = c.post(f"/api/v1/setups/{s['id']}/cam")
    assert r.status_code == 503


def test_sim_enqueue_broker_down(monkeypatch):
    c = TestClient(app)
    p = c.post("/api/v1/projects", headers={"Idempotency-Key": "t-sim-1"}, json={"name": "P", "type": "part", "source": "prompt"}).json()
    s = c.post("/api/v1/setups", headers={"Idempotency-Key": "t-sim-2"}, json={"project_id": p["id"], "name": "Top", "wcs": "G54"}).json()

    def fake_delay(_):
        raise RuntimeError("broker down")

    from app.routers import setups as setups_router
    monkeypatch.setattr(setups_router.setup_sim_task, "delay", fake_delay)
    r = c.post(f"/api/v1/setups/{s['id']}/simulate")
    assert r.status_code == 503


def test_post_enqueue_broker_down_or_guard(monkeypatch):
    c = TestClient(app)
    p = c.post("/api/v1/projects", headers={"Idempotency-Key": "t-post-err-1"}, json={"name": "P", "type": "part", "source": "prompt"}).json()
    s = c.post("/api/v1/setups", headers={"Idempotency-Key": "t-post-err-2"}, json={"project_id": p["id"], "name": "Top", "wcs": "G54"}).json()
    # guard
    r = c.post(f"/api/v1/setups/{s['id']}/post")
    assert r.status_code == 409
    # simulate sim_ok then broker error
    from app.db import db_session
    from app.models_project import Setup
    with db_session() as sess:
        st = sess.get(Setup, s['id'])
        st.status = "sim_ok"
        sess.commit()

    def fake_delay(_):
        raise RuntimeError("broker down")

    from app.routers import setups as setups_router
    monkeypatch.setattr(setups_router.setup_post_task, "delay", fake_delay)
    r2 = c.post(f"/api/v1/setups/{s['id']}/post")
    assert r2.status_code == 503
"""
