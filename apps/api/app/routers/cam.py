from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field

from ..db import db_session
from ..models import Job
from ..schemas.cam import CamJobCreate
from ..services.job_control import is_queue_paused
from ..settings import app_settings as appset
from ..tasks.cam import cam_generate

router = APIRouter(prefix="/api/v1/cam", tags=["CAM/G-code"])


class GCodeRequest(BaseModel):
    controller: str = Field(..., description="Post-processor adı (ör. fanuc/marlin)")
    program_name: str = Field(..., description="Program adı")
    parameters: dict = Field(default_factory=dict)


class GCodeResponse(BaseModel):
    success: bool
    message: str
    artefact_url: str | None = None


@router.post("/gcode", response_model=dict)
def generate_gcode(body: CamJobCreate, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    if appset.require_idempotency and not idempotency_key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Idempotency-Key başlığı zorunludur")
    if is_queue_paused("freecad"):
        raise HTTPException(status_code=409, detail="freecad kuyruğu geçici olarak duraklatıldı.")
    with db_session() as s:
        if idempotency_key:
            exist = s.query(Job).filter_by(idempotency_key=idempotency_key, type="cam").first()
            if exist:
                from ..audit import audit
                audit("idempotent_hit", job_id=exist.id, key=idempotency_key)
                return {"job_id": exist.id, "idempotent_hit": True}
        params = body.model_dump()
        job = Job(
            type="cam",
            status="pending",
            metrics={"params": params, "created_at": datetime.utcnow().isoformat(), "queue": "cpu"},
            idempotency_key=idempotency_key,
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        cam_generate.delay(job.id)
        return {"job_id": job.id}


