from __future__ import annotations

from datetime import datetime

from billiard.exceptions import SoftTimeLimitExceeded
from opentelemetry import trace

from ..audit import audit
from ..db import db_session
from ..freecad.generate import generate_and_validate
from ..logging_setup import get_logger
from ..metrics import failures_total, job_latency_seconds, queue_wait_seconds, retried_total
from ..models import Job
from ..schemas.cad import AssemblyRequestV1
from ..services.dlq import push_dead
from ..settings import app_settings as appset
from ..storage import upload_and_sign
from .worker import celery_app

logger = get_logger(__name__)


@celery_app.task(
    bind=True,
    name="assembly.generate",
    queue="freecad",
    acks_late=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=appset.task_soft_limits.get("freecad", 870),
    time_limit=appset.task_time_limits.get("freecad", 900),
)
def assembly_generate(self, job_id: int) -> dict:
    with db_session() as s:
        job = s.get(Job, job_id)
        if not job:
            return {"error": "job yok"}
        job.status = "running"
        job.started_at = datetime.utcnow()
        job.task_id = self.request.id
        # Kuyruk bekleme süresi ölçümü: created_at alanımız yoksa metrics.created_at ile yaklaşık ölçüm
        if not job.metrics:
            job.metrics = {}
        job.metrics.setdefault("created_at", datetime.utcnow().isoformat())
        s.commit()

    try:
        tracer = trace.get_tracer(__name__)
        started = datetime.utcnow()
        req = AssemblyRequestV1.model_validate(job.metrics.get("request"))  # request ham hali metrics içinde
        pid_file = f"/tmp/{self.request.id}.pid"
        with tracer.start_as_current_span("freecad.generate_validate") as span:
            fcstd_path, metrics = generate_and_validate(req, pid_file=pid_file)
            span.set_attribute("job_id", job_id)
            span.set_attribute("type", "assembly")
            if "elapsed_ms" in metrics:
                span.set_attribute("elapsed_ms", metrics["elapsed_ms"])
        artefact = upload_and_sign(fcstd_path, "fcstd")

        with db_session() as s:
            job = s.get(Job, job_id)
            job.status = "succeeded"
            job.finished_at = datetime.utcnow()
            job.metrics = {**(job.metrics or {}), **metrics}
            job.artefacts = [{
                "type": artefact["type"],
                "s3_key": artefact["s3_key"],
                "size": artefact["size"],
                "sha256": artefact["sha256"],
            }]  # type: ignore[assignment]
            s.commit()
        # Metrikler
        if job.started_at and job.finished_at:
            job_latency_seconds.labels(type="assembly", status="succeeded").observe((job.finished_at - job.started_at).total_seconds())
        if job.started_at and job.metrics and job.metrics.get("created_at"):
            try:
                created = datetime.fromisoformat(job.metrics["created_at"]).replace(tzinfo=None)
                queue_wait_seconds.labels(queue=job.metrics.get("queue", "freecad")).observe((job.started_at - created).total_seconds())
            except Exception:
                # created_at parse edilemezse atla
                ...
        audit("task.success", job_id=job_id, task="assembly.generate")
        return {"ok": True}
    except SoftTimeLimitExceeded:
        with db_session() as s:
            job = s.get(Job, job_id)
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            job.error_message = "Zaman sınırı aşıldı"
            s.commit()
        push_dead(job_id, "assembly.generate", "time_limit")
        failures_total.labels(task="assembly.generate", reason="time_limit").inc()
        audit("task.time_limit_hit", job_id=job_id, task="assembly.generate")
        if self.request.retries < self.request.max_retries:
            retried_total.labels(task="assembly.generate").inc()
        raise
    except Exception as e:
        with db_session() as s:
            job = s.get(Job, job_id)
            job.status = "failed"
            job.finished_at = datetime.utcnow()
            job.error_message = str(e)
            s.commit()
        push_dead(job_id, "assembly.generate", str(e))
        failures_total.labels(task="assembly.generate", reason=type(e).__name__).inc()
        audit("dlq.push", job_id=job_id, task="assembly.generate", reason=str(e))
        if getattr(self.request, "retries", 0) < getattr(self.request, "max_retries", 0):
            retried_total.labels(task="assembly.generate").inc()
        raise


