from __future__ import annotations

from celery import shared_task
import tempfile

from ..db import SessionLocal
# from ..models_project import Project, ProjectFile, FileKind, ProjectStatus  # Module not found
# Temporary stub for missing models
class Project: pass
class ProjectFile: pass  
class FileKind: pass
class ProjectStatus: pass
from ..storage import upload_and_sign
from ..freecad.cad_build import build_from_plan


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=3, acks_late=True, queue='cpu')
def cad_build_task(self, project_id: int):
    db = SessionLocal()
    try:
        p = db.query(Project).get(project_id)
        if not p or not p.summary_json:
            raise RuntimeError("Plan bulunamadı.")
        plan = (p.summary_json or {}).get("plan") or {}
        with tempfile.TemporaryDirectory() as d:
            paths, stats = build_from_plan(plan, d)
            out = {}
            for kind, path in paths.items():
                if not path:
                    continue
                art = upload_and_sign(path, type=f"cad/{kind}")
                f = ProjectFile(
                    project_id=p.id,
                    kind=FileKind.cad,
                    s3_key=art["s3_key"],
                    size=art["size"],
                    sha256=art["sha256"],
                    version=(plan or {}).get("rev") or "v1",
                    notes=kind,
                )
                db.add(f)
                db.commit()
                out[kind] = art.get("signed_url")
            p.status = ProjectStatus.cad_ready if stats.get("ok") else ProjectStatus.error
            p.summary_json = {**(p.summary_json or {}), "cad_stats": stats, "cad_artifacts": out}
            db.commit()
            return {"project_id": p.id, "artifacts": out, "stats": stats}
    finally:
        db.close()


