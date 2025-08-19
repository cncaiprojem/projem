from __future__ import annotations

from datetime import datetime
import time

from ..freecad.m18_builder import build_setup_job
from ..db import db_session
from ..models_project import Setup
from ..metrics import cam3d_duration_seconds
from ..audit import audit


def setup_cam_task_run(setup_id: int):
    started = time.time()
    with db_session() as s:
        st = s.get(Setup, setup_id)
        if not st:
            return {"error": "setup yok"}
        audit("setup.cam3d.start", setup_id=setup_id)
    res = build_setup_job(setup_id=setup_id, fast_mode=True)
    with db_session() as s:
        st = s.get(Setup, setup_id)
        st.status = "cam_ready"
        s.commit()
    cam3d_duration_seconds.labels(status="succeeded").observe(time.time() - started)
    audit("setup.cam3d.finish", setup_id=setup_id)
    return {"ok": True, "setup_id": setup_id, "fcstd": str(res.fcstd_path)}
