from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String

from ..db import db_session
from ..models import Base, Job
from ..tasks.worker import celery_app


class DeadJob(Base):
    __tablename__ = "dead_jobs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, nullable=False)
    task = Column(String(255), nullable=False)
    reason = Column(String(1024), nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


def push_dead(job_id: int, task: str, reason: str, ts: datetime | None = None) -> None:
    with db_session() as s:
        dj = DeadJob(job_id=job_id, task=task, reason=reason, created_at=ts or datetime.utcnow())
        s.add(dj)
        s.commit()


def list_dead(limit: int = 100, offset: int = 0) -> list[dict]:
    with db_session() as s:
        q = s.query(DeadJob).order_by(DeadJob.id.desc()).offset(offset).limit(limit)
        return [
            {"id": d.id, "job_id": d.job_id, "task": d.task, "reason": d.reason, "created_at": d.created_at.isoformat()} for d in q.all()
        ]


def requeue(job_id: int) -> bool:
    with db_session() as s:
        job = s.get(Job, job_id)
        if not job:
            return False
        # Kuyruğu job türüne göre seçelim
        queue = "freecad" if job.type == "assembly" else ("sim" if job.type == "sim" else "cpu")
        task_name = {
            "assembly": "app.tasks.assembly.assembly_generate",
            "sim": "app.tasks.sim.sim_generate",
            "cam": "app.tasks.cam.cam_generate",
        }.get(job.type)
        if not task_name:
            return False
        celery_app.send_task(task_name, args=[job_id], queue=queue)
        return True


