from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import random
import string
import time
from statistics import median
from typing import Dict, List

import requests


def rand_key(prefix: str, n: int = 10) -> str:
    return f"{prefix}-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def p50p95(values: List[float]) -> Dict[str, float]:
    if not values:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0}
    s = sorted(values)

    def perc(p):
        k = int(len(s) * p)
        k = min(max(k, 0), len(s) - 1)
        return s[k]

    return {"p50": perc(0.5), "p95": perc(0.95), "p99": perc(0.99)}


def do_chain(base_url: str, prefix: str, timeout: int) -> Dict:
    t0 = time.time()
    headers = {"Idempotency-Key": rand_key(prefix)}
    asm_body = {
        "type": "planetary_gearbox",
        "spec": {
            "stages": [{"ratio": 3.16}, {"ratio": 3.16}, {"ratio": 10.0}],
            "overall_ratio": 100.0,
            "power_kW": 10,
            "materials": {"gear": "steel", "housing": "aluminum"},
            "outputs": {"torqueNm": 1000, "radialN": 4000, "axialN": 2000},
        },
    }
    r = requests.post(
        f"{base_url}/api/v1/assemblies", json=asm_body, headers=headers, timeout=timeout
    )
    r.raise_for_status()
    asm_id = r.json()["job_id"]

    headers = {"Idempotency-Key": rand_key(prefix)}
    cam_body = {
        "assembly_job_id": asm_id,
        "post": "grbl",
        "tool_diameter_mm": 6.0,
        "spindle_rpm": 8000,
        "feed_mm_min": 600,
        "plunge_mm_min": 200,
        "stepdown_mm": 1.0,
        "safe_z_mm": 5.0,
        "stock_margin_mm": 2.0,
        "units": "mm",
    }
    r = requests.post(
        f"{base_url}/api/v1/cam/gcode", json=cam_body, headers=headers, timeout=timeout
    )
    r.raise_for_status()
    cam_id = r.json()["job_id"]

    headers = {"Idempotency-Key": rand_key(prefix)}
    sim_body = {
        "assembly_job_id": asm_id,
        "gcode_job_id": cam_id,
        "resolution_mm": 0.8,
        "method": "voxel",
    }
    r = requests.post(
        f"{base_url}/api/v1/sim/simulate", json=sim_body, headers=headers, timeout=timeout
    )
    r.raise_for_status()
    sim_id = r.json()["job_id"]

    # Bekle: sim tamamlanana kadar polling
    for _ in range(timeout // 5):
        sj = requests.get(f"{base_url}/api/v1/jobs/{sim_id}", timeout=30)
        if sj.status_code == 200:
            data = sj.json()
            if data.get("status") in ("succeeded", "failed"):
                elapsed = time.time() - t0
                return {
                    "ok": data.get("status") == "succeeded",
                    "elapsed": elapsed,
                    "sim_id": sim_id,
                }
        time.sleep(5)
    return {"ok": False, "elapsed": time.time() - t0, "sim_id": sim_id}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--chain", type=str, default="assembly,cam,sim")
    ap.add_argument("--idprefix", type=str, default="bench")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--base-url", type=str, default="http://api:8000")
    args = ap.parse_args()

    results: List[Dict] = []
    t0 = time.time()
    with cf.ThreadPoolExecutor(max_workers=args.n) as ex:
        futs = [
            ex.submit(do_chain, args.base_url, args.idprefix, args.timeout) for _ in range(args.n)
        ]
        for f in cf.as_completed(futs):
            try:
                results.append(f.result())
            except Exception as e:
                results.append({"ok": False, "error": str(e), "elapsed": None})

    ok_list = [r for r in results if r.get("ok")]
    elapsed = [r.get("elapsed", 0.0) for r in results if r.get("elapsed")]
    stats = p50p95(elapsed)
    success_rate = len(ok_list) / len(results) if results else 0

    os.makedirs("reports", exist_ok=True)
    with open("reports/load_result.json", "w", encoding="utf-8") as f:
        json.dump(
            {
                "results": results,
                "stats": stats,
                "success_rate": success_rate,
                "total_s": time.time() - t0,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    with open("reports/load_result.md", "w", encoding="utf-8") as f:
        f.write("# Yük Testi Sonuçları\n\n")
        f.write(f"Toplam zincir: {len(results)}\n\n")
        f.write(f"Başarı oranı: {success_rate * 100:.1f}%\n\n")
        f.write(f"p50: {stats['p50']:.1f}s, p95: {stats['p95']:.1f}s, p99: {stats['p99']:.1f}s\n")

    # Exit policy
    if success_rate < 0.9 or stats.get("p95", 99999) > 900:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
