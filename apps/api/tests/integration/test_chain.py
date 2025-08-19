from __future__ import annotations

import os
import pytest
from starlette.testclient import TestClient

from app.main import app


@pytest.mark.skipif(os.getenv("CI") == "true", reason="FreeCADCmd gerektirir")
def test_chain_end_to_end_smoke():
    client = TestClient(app)
    # Minimal assembly isteği (gerçek FreeCADCmd gerektirir; smoke amaçlı ve ortam kurulunca aktif edilir)
    payload = {
        "type": "planetary_gearbox",
        "spec": {
            "stages": [{"ratio": 3.0}],
            "overall_ratio": 3.0,
            "power_kW": 1.0,
            "materials": {"gear": "steel", "housing": "aluminum"},
            "outputs": {"torqueNm": 10, "radialN": 10, "axialN": 5},
        },
    }
    r = client.post("/api/v1/assemblies", json=payload, headers={"Idempotency-Key": "itest1"})
    assert r.status_code in (200, 422, 409)
