# LEGACY TEST FILE - DISABLED
# This test file references legacy models not in Task Master ERD
"""
from fastapi.testclient import TestClient
from app.main import app
from app.db import db_session
from app.models_project import Setup


def test_post_requires_sim_ok():
    c = TestClient(app)
    # Proje ve setup oluştur
    r = c.post("/api/v1/projects", headers={"Idempotency-Key": "t-post-1"}, json={"name": "P", "type": "part", "source": "prompt"})
    pid = r.json()["id"]
    r2 = c.post("/api/v1/setups", headers={"Idempotency-Key": "t-post-2"}, json={"project_id": pid, "name": "Top", "wcs": "G54"})
    sid = r2.json()["id"]
    # Sim OK olmadan post dene -> 409
    r3 = c.post(f"/api/v1/setups/{sid}/post")
    assert r3.status_code == 409
    # DB'de sim_ok'a çek ve tekrar dene -> 202
    with db_session() as s:
        st = s.get(Setup, sid)
        st.status = "sim_ok"
        s.commit()
    r4 = c.post(f"/api/v1/setups/{sid}/post")
    assert r4.status_code == 202
"""

