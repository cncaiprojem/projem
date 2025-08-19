from __future__ import annotations

from celery import shared_task
import time
from datetime import datetime

from ..db import db_session
from ..models_project import Setup
from ..metrics import simulate3d_duration_seconds, m18_holder_collisions_total
from ..audit import audit
from ..sim.holder_check import Segment, swept_cylinder_min_clearance
from ..repos.m18 import add_collision


@shared_task(bind=True, queue="sim")
def setup_sim_task(self, setup_id: int):
    started = time.time()
    with db_session() as s:
        st = s.get(Setup, setup_id)
        if not st:
            return {"error": "setup yok"}
        audit("setup.sim3d.start", setup_id=setup_id)
    # Placeholder path segments
    segs = [Segment(0, 0, 0, 10, 0, 0), Segment(10, 0, 0, 10, 10, 0)]
    min_clear, hits = swept_cylinder_min_clearance(segs, holder_diameter_mm=30.0, clearance_mm=10.0)
    with db_session() as s:
        st = s.get(Setup, setup_id)
        if hits:
            st.status = "draft"  # fail policy: post kilit
            for h in hits:
                add_collision(
                    s,
                    setup_id,
                    phase="sim",
                    ctype="holder",
                    severity="warn",
                    details={"index": h.get("index"), "clear": h.get("clear")},
                )
        else:
            st.status = "sim_ok"
        s.commit()
    simulate3d_duration_seconds.labels(status="succeeded").observe(time.time() - started)
    if hits:
        m18_holder_collisions_total.labels(severity="warn").inc(len(hits))
    audit("setup.sim3d.ok" if not hits else "setup.sim3d.fail(holder)", setup_id=setup_id)
    return {"ok": True, "hits": hits}
