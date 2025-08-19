from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict

from .worker import celery_app

from ..config import settings
from ..db import db_session
from ..logging_setup import get_logger
from ..models import Job
from ..storage import upload_and_sign, get_s3_client
from ..freecad.service import detect_freecad
from ..freecad.path_job import make_path_job
from ..services.dlq import push_dead
from ..audit import audit
from ..metrics import job_latency_seconds, failures_total, queue_wait_seconds, retried_total
from opentelemetry import trace
from billiard.exceptions import SoftTimeLimitExceeded


logger = get_logger(__name__)


def lint_gcode(text: str, params: Dict) -> Dict:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise RuntimeError("G-code boş")
    if not any(ln.startswith("G0") or ln.startswith("G1") for ln in lines):
        raise RuntimeError("G0/G1 komutları bulunamadı")
    # İlk G1 öncesi F set edilmiş mi
    f_set = False
    for ln in lines:
        if "F" in ln:
            f_set = True
            break
        if ln.startswith("G1"):
            break
    if not f_set:
        raise RuntimeError("İlk G1 öncesinde ilerleme (F) ayarı bulunamadı")
    txt_lower = "\n".join(lines).lower()
    if "nan" in txt_lower or "inf" in txt_lower:
        raise RuntimeError("Geçersiz sayı (NaN/Inf) içeriyor")
    units = params.get("units", "mm")
    if units == "mm" and not any("G21" in ln for ln in lines[:20]):
        raise RuntimeError("Birim bildirimi (G21) bulunamadı")
    if units == "inch" and not any("G20" in ln for ln in lines[:20]):
        raise RuntimeError("Birim bildirimi (G20) bulunamadı")
    # Basit bbox kontrolü: X/Y/Z değerlerini kaba regex olmadan pars etmek zor; hızlı kontrol: sınır anahtarlarına göre döndür
    return {"lines": len(lines)}


@celery_app.task(
    bind=True,
    name="cam.generate",
    queue="cpu",
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def cam_generate(self, job_id: int) -> dict:
    with db_session() as s:
        job = s.get(Job, job_id)
        if not job:
            return {"error": "job yok"}
        job.status = "running"
        job.started_at = datetime.utcnow()
        params: Dict = job.metrics.get("params", {}) if job.metrics else {}
        assembly_job_id = params.get("assembly_job_id")
        s.commit()

    # assembly job'dan fcstd artefaktını bul
    with db_session() as s:
        assembly = s.get(Job, assembly_job_id)
        if not assembly or not assembly.artefacts:
            raise RuntimeError("Assembly işinin artefaktı bulunamadı")
        a0 = assembly.artefacts[0]
        s3_key = a0.get("s3_key")
        if not s3_key:
            raise RuntimeError("FCStd s3_key eksik")

    # indir
    s3 = get_s3_client()
    tmp_dir = Path("/tmp/cam")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    fcstd_path = tmp_dir / "assembly.fcstd"
    s3.download_file(settings.s3_bucket_name, s3_key, str(fcstd_path))

    # FreeCADCmd
    fc = detect_freecad()
    if not fc.found or not fc.path:
        raise RuntimeError("FreeCADCmd bulunamadı")

    try:
        # Path Job → gcode
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span("cam.path_job") as span:
            gcode_path, stats = make_path_job(
                fc.path,
                fcstd_path,
                params,
                params.get("post", "grbl"),
                settings.freecad_timeout_seconds,
            )
            span.set_attribute("job_id", job_id)
            span.set_attribute("type", "cam")
        text = gcode_path.read_text(encoding="utf-8", errors="ignore")
        lint = lint_gcode(text, params)

        art = upload_and_sign(gcode_path, "gcode")
        with db_session() as s:
            job = s.get(Job, job_id)
            job.status = "succeeded"
            job.finished_at = datetime.utcnow()
            job.metrics = {**(job.metrics or {}), **stats, **lint}
            job.artefacts = [
                {
                    "type": art["type"],
                    "s3_key": art["s3_key"],
                    "size": art["size"],
                    "sha256": art["sha256"],
                }
            ]
            s.commit()
        if job.started_at and job.finished_at:
            job_latency_seconds.labels(type="cam", status="succeeded").observe(
                (job.finished_at - job.started_at).total_seconds()
            )
        if job.started_at and (job.metrics or {}).get("created_at"):
            try:
                created = datetime.fromisoformat(job.metrics["created_at"]).replace(tzinfo=None)
                queue_wait_seconds.labels(queue=(job.metrics or {}).get("queue", "cpu")).observe(
                    (job.started_at - created).total_seconds()
                )
            except Exception:
                ...
        audit("task.success", job_id=job_id, task="cam.generate")
        return {"ok": True}
    except SoftTimeLimitExceeded:
        with db_session() as s:
            job = s.get(Job, job_id)
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            job.error_message = "Zaman sınırı aşıldı"
            s.commit()
        push_dead(job_id, "cam.generate", "time_limit")
        failures_total.labels(task="cam.generate", reason="time_limit").inc()
        if self.request.retries < self.request.max_retries:
            retried_total.labels(task="cam.generate").inc()
        audit("task.time_limit_hit", job_id=job_id, task="cam.generate")
        raise
    except Exception as e:
        with db_session() as s:
            job = s.get(Job, job_id)
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            job.error_message = str(e)
            s.commit()
        push_dead(job_id, "cam.generate", str(e))
        failures_total.labels(task="cam.generate", reason=type(e).__name__).inc()
        if getattr(self.request, "retries", 0) < getattr(self.request, "max_retries", 0):
            retried_total.labels(task="cam.generate").inc()
        audit("dlq.push", job_id=job_id, task="cam.generate", reason=str(e))
        raise
