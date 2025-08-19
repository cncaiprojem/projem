from __future__ import annotations

import argparse
import json
import random
import time
from typing import Dict, List

import requests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--mode", type=str, default="random-fail")
    ap.add_argument("--base-url", type=str, default="http://api:8000")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    random.seed(args.seed)

    base = args.base_url
    created: List[int] = []
    dlq_before = requests.get(f"{base}/api/v1/admin/dlq").json().get("items", [])

    # 1) N adet assembly → cam → sim zinciri başlat
    for i in range(args.n):
        headers = {"Idempotency-Key": f"chaos-{i}-{random.randint(1000, 9999)}"}
        asm = {
            "type": "planetary_gearbox",
            "spec": {
                "stages": [{"ratio": 3.16}],
                "overall_ratio": 3.16,
                "power_kW": 1,
                "materials": {"gear": "steel", "housing": "aluminum"},
                "outputs": {"torqueNm": 10, "radialN": 10, "axialN": 5},
            },
        }
        r = requests.post(f"{base}/api/v1/assemblies", json=asm, headers=headers)
        asm_id = r.json()["job_id"]
        created.append(asm_id)

    # 2) Rastgele pause/resume freecad kuyruğu
    requests.post(f"{base}/api/v1/jobs/queues/freecad/pause")
    time.sleep(10)
    requests.post(f"{base}/api/v1/jobs/queues/freecad/resume")

    # 3) Rastgele 1-2 işi cancel
    cancels = random.sample(created, k=min(2, len(created)))
    for jid in cancels:
        requests.post(f"{base}/api/v1/jobs/{jid}/cancel")

    time.sleep(5)

    # 4) DLQ kontrol ve requeue
    dlq_list = requests.get(f"{base}/api/v1/admin/dlq").json().get("items", [])
    requeued = 0
    for d in dlq_list:
        ok = requests.post(f"{base}/api/v1/admin/dlq/{d['job_id']}/requeue").ok
        if ok:
            requeued += 1

    report = {
        "created": len(created),
        "dlq_before": len(dlq_before),
        "dlq_after": len(dlq_list),
        "requeued": requeued,
    }
    print(json.dumps(report))
    if requeued == 0 and len(dlq_list) > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
