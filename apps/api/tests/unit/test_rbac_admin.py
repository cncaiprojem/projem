from __future__ import annotations

from starlette.testclient import TestClient

from app.main import app
from app.security.oidc import Principal, get_principal


def test_admin_routes_forbidden_for_viewer():
    client = TestClient(app)
    # Dev modda viewer rolü gelir
    r = client.get("/api/v1/admin/dlq")
    assert r.status_code == 403
    r = client.post("/api/v1/jobs/1/cancel")
    assert r.status_code == 403


def test_admin_routes_allowed_for_admin(monkeypatch):
    client = TestClient(app)

    def fake_principal():
        return Principal(sub="u", email="a@b", roles=["admin"])  # type: ignore

    app.dependency_overrides[get_principal] = fake_principal
    try:
        r = client.get("/api/v1/admin/dlq")
        assert r.status_code in (200, 204)
    finally:
        app.dependency_overrides.clear()
