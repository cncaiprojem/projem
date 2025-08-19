from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..db import db_session
from ..models import Job
from ..security.oidc import require_role
from ..services.job_control import cancel_job, queue_pause, queue_resume
from ..storage import presigned_url

router = APIRouter(prefix="/api/v1/jobs", tags=["İşler"])


@router.get("")
def list_jobs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), type: str | None = None):
    with db_session() as s:
        q = s.query(Job)
        if type:
            q = q.filter(Job.type == type)
        q = q.order_by(Job.id.desc()).offset(offset).limit(limit)
        items = []
        for j in q.all():
            items.append({
                "id": j.id,
                "type": j.type,
                "status": j.status,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
                "metrics": j.metrics,
            })
        return {"items": items, "limit": limit, "offset": offset}

@router.get("/{job_id}")
def get_job(job_id: int):
    with db_session() as s:
        job: Job | None = s.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="İş bulunamadı")
        artefacts = []
        if job.artefacts:
            for a in job.artefacts:
                url = presigned_url(a.get("s3_key", "")) if a.get("s3_key") else None
                artefacts.append({**a, "signed_url": url})
        return {
            "id": job.id,
            "type": job.type,
            "status": job.status,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "metrics": job.metrics,
            "artefacts": artefacts or None,
        }


@router.post("/{job_id}/cancel", dependencies=[Depends(require_role("admin"))])
def cancel(job_id: int):
    ok = cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="İş bulunamadı")
    return {"status": "cancelled"}


@router.post("/queues/{name}/pause", dependencies=[Depends(require_role("admin"))])
def pause_queue(name: str):
    queue_pause(name)
    return {"queue": name, "status": "paused"}


@router.post("/queues/{name}/resume", dependencies=[Depends(require_role("admin"))])
def resume_queue(name: str):
    queue_resume(name)
    return {"queue": name, "status": "resumed"}


