from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

from celery import shared_task

from ..db import db_session
from ..models import Job
from ..llm_router import generate_structured
from ..freecad.generate import (
    validate_script_security,
    build_freecad_python,
    run_freecad_cmd,
    build_freecad_validation,
)
from ..storage import upload_and_sign


@shared_task(name="design.orchestrate", queue="cpu", time_limit=600)
def design_orchestrate(job_id: int):
    with db_session() as s:
        job = s.get(Job, job_id)
        if not job:
            return
        job.status = "running"
        s.commit()
    try:
        params = (job.metrics or {}).get("params") if job and job.metrics else None
        brief = (params or {}).get("brief") if isinstance(params, dict) else {}
        data, meta = generate_structured(brief or {})
        script_body = data.get("script", "")
        validate_script_security(script_body)
        full_script = build_freecad_python(script_body)
        out_dir = Path(tempfile.mkdtemp())
        out_fcstd = out_dir / "design.fcstd"
        res1 = run_freecad_cmd("FreeCADCmd", full_script, out_fcstd, 600, pid_file=None)
        if res1["returncode"] != 0:
            raise RuntimeError("FreeCAD üretim hatası")
        # doğrulama
        res2 = run_freecad_cmd(
            "FreeCADCmd", build_freecad_validation(), out_fcstd, 120, pid_file=None
        )
        if res2["returncode"] != 0:
            raise RuntimeError("FreeCAD doğrulama hatası")
        # artefakt yükle
        artefacts = []
        artefacts.append(upload_and_sign(out_fcstd, "fcstd"))
        bom = data.get("bom") or []
        bom_path = out_dir / "BOM.json"
        bom_path.write_text(json.dumps(bom, ensure_ascii=False))
        artefacts.append(upload_and_sign(bom_path, "bom"))
        with db_session() as s:
            job = s.get(Job, job_id)
            if not job:
                return
            met = job.metrics or {}
            met.update(
                {
                    "elapsed_ms": res1.get("elapsed_ms"),
                    "model_name": meta.get("model_name"),
                    "token_in": meta.get("token_input"),
                    "token_out": meta.get("token_output"),
                    "escalated": meta.get("escalated"),
                }
            )
            job.metrics = met
            job.artefacts = artefacts
            job.status = "success"
            job.finished_at = datetime.utcnow()
            s.commit()
    except Exception as e:
        with db_session() as s:
            job = s.get(Job, job_id)
            if not job:
                return
            job.status = "failed"
            job.error_message = str(e)
            job.finished_at = datetime.utcnow()
            s.commit()
