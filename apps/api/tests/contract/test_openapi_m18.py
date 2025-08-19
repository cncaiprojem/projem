from fastapi.testclient import TestClient
from app.main import app


def test_openapi_contains_m18_paths():
    client = TestClient(app)
    data = client.get("/openapi.json").json()
    paths = data.get("paths", {})
    assert "/api/v1/setups" in paths
    assert "/api/v1/setups/{setup_id}/plan-ops3d" in paths
    assert "/api/v1/setups/{setup_id}/cam" in paths
    assert "/api/v1/setups/{setup_id}/simulate" in paths
    assert "/api/v1/setups/{setup_id}/post" in paths
    assert "/api/v1/fixtures" in paths
