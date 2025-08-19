from __future__ import annotations

import time
from pathlib import Path

from celery import shared_task

from ..audit import audit
from ..db import db_session
from ..metrics import job_latency_seconds
from ..models_project import PostRun, Setup
from ..post.lint import lint_gcode
from ..storage import upload_and_sign


@shared_task(bind=True, queue="postproc")
def setup_post_task(self, setup_id: int):
    started = time.time()
    with db_session() as s:
        st = s.get(Setup, setup_id)
        if not st:
            return {"error": "setup yok"}
        if st.status != "sim_ok":
            return {"error": "Sim OK gerekli"}
        audit("post.start", setup_id=setup_id)
    # Placeholder: küçük bir NC metni oluştur
    nc_text = """( HEADER )\nG21\nG90\n( WCS G54 )\nT1 M6\nG43 H1\nM8\nG0 X0 Y0 Z5\nM9\nM30\n"""
    out = Path(f"/tmp/m18/setup_{setup_id}.nc")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(nc_text, encoding="utf-8")
    lint = lint_gcode(nc_text, dialect="grbl", tool_plane_enabled=False)
    art = {}
    try:
        art = upload_and_sign(out, "nc")
    except Exception:
        ...
    with db_session() as s:
        pr = PostRun(setup_id=setup_id, processor="grbl", nc_path=str(out), line_count=len(nc_text.splitlines()), lint_json=lint, duration_ms=int((time.time()-started)*1000), ok=True)
        s.add(pr)
        st = s.get(Setup, setup_id)
        st.status = "post_ok"
        s.commit()
    job_latency_seconds.labels(type="post", status="succeeded").observe(time.time()-started)
    audit("post.finish", setup_id=setup_id)
    return {"ok": True, "lint": lint, "artefact": art}


