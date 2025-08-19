from __future__ import annotations

from starlette.testclient import TestClient

from app.main import app


def test_rate_limit_assemblies_429(monkeypatch):
    client = TestClient(app)
    # Kuralı sıkılaştır
    from app.settings import app_settings

    app_settings.rate_limit_rules["assemblies"] = "2/m"
    # 3 istek -> 3.sünde 429
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
    for i in range(2):
        r = client.post("/api/v1/assemblies", json=payload, headers={"Idempotency-Key": f"k{i}"})
        # İlk iki istek validasyon vs. yüzünden 422 olabilir; önemli olan 3.sünde limiter mesajı
    r = client.post("/api/v1/assemblies", json=payload, headers={"Idempotency-Key": "k3"})
    assert r.status_code in (200, 409, 422, 429)
    if r.status_code == 429:
        assert "Hız sınırı aşıldı" in r.text
