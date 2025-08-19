from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, status
from datetime import datetime
from ..config import settings
from ..settings import app_settings as appset

from ..db import db_session
from ..models import Job
from ..schemas.sim import SimJobCreate
from ..models import Job
from ..services.job_control import is_queue_paused
from ..tasks.sim import sim_generate


router = APIRouter(prefix="/api/v1/sim", tags=["Simülasyon"])


@router.post("/simulate", response_model=dict)
def simulate(
    body: SimJobCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")
):
    if appset.require_idempotency and not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key başlığı zorunludur",
        )
    if is_queue_paused("sim"):
        raise HTTPException(status_code=409, detail="sim kuyruğu geçici olarak duraklatıldı.")
    with db_session() as s:
        if idempotency_key:
            exist = s.query(Job).filter_by(idempotency_key=idempotency_key, type="sim").first()
            if exist:
                from ..audit import audit

                audit("idempotent_hit", job_id=exist.id, key=idempotency_key)
                return {"job_id": exist.id, "idempotent_hit": True}
        params = body.model_dump()
        job = Job(
            type="sim",
            status="pending",
            metrics={"params": params, "created_at": datetime.utcnow().isoformat(), "queue": "sim"},
            idempotency_key=idempotency_key,
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        sim_generate.delay(job.id)
        return {"job_id": job.id}
