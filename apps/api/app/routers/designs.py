from __future__ import annotations

from datetime import datetime
from fastapi import APIRouter, Header, HTTPException, status, Depends

from ..db import db_session
from ..models import Job
from ..schemas.design import DesignJobCreate, DesignBrief, DesignAnalysisQuestion, DesignJobResult
from ..tasks.design import design_orchestrate
from ..services.job_control import is_queue_paused
from ..dependencies.auth_dependencies import require_scopes, require_read_access, optional_auth
from ..middleware.jwt_middleware import AuthenticatedUser


router = APIRouter(prefix="/api/v1/designs", tags=["Tasarım (P2D)"])


@router.post("/analyze", response_model=list[DesignAnalysisQuestion])
def analyze(
    body: DesignBrief,
    current_user: AuthenticatedUser = Depends(require_scopes("designs:read"))
):
  """Design analysis endpoint - requires designs:read scope."""
  qs: list[DesignAnalysisQuestion] = []
  text = (body.prompt or '').strip()
  if not text:
    qs.append(DesignAnalysisQuestion(id="brief.prompt", text="Lütfen kısa bir tasarım tanımı girin."))
  if body.targets and body.targets.get('ratio') is None:
    qs.append(DesignAnalysisQuestion(id="targets.ratio", text="Hedef oran nedir?"))
  if body.targets and body.targets.get('power_kW') is None:
    qs.append(DesignAnalysisQuestion(id="targets.power_kW", text="Güç (kW) hedefi nedir?"))
  if body.targets and body.targets.get('torqueNm') is None:
    qs.append(DesignAnalysisQuestion(id="targets.torqueNm", text="Tork (Nm) hedefi nedir?"))
  return qs[:5]


@router.post("", response_model=dict)
def create(
    body: DesignJobCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_scopes("designs:write"))
):
  """Create design job - requires designs:write scope."""
  if is_queue_paused('cpu'):
    raise HTTPException(status_code=409, detail="cpu kuyruğu geçici olarak duraklatıldı.")
  with db_session() as s:
    if idempotency_key:
      exist = s.query(Job).filter_by(idempotency_key=idempotency_key, type='design').first()
      if exist:
        return {"job_id": exist.id, "idempotent_hit": True}
    job = Job(
      type='design',
      status='pending',
      metrics={
        "params": body.model_dump(), 
        "created_at": datetime.utcnow().isoformat(), 
        "queue": "cpu",
        "user_id": current_user.user_id,
        "user_role": current_user.role.value
      },
      idempotency_key=idempotency_key,
    )
    s.add(job)
    s.commit()
    s.refresh(job)
    design_orchestrate.delay(job.id)
    return {"job_id": job.id}


@router.get("/{job_id}", response_model=DesignJobResult)
def get(
    job_id: int,
    current_user: AuthenticatedUser = Depends(require_scopes("designs:read"))
):
  """Get design job - requires designs:read scope."""
  with db_session() as s:
    job = s.get(Job, job_id)
    if not job:
      raise HTTPException(status_code=404, detail="İş bulunamadı")
    artefacts = job.artefacts or []
    return {
      "job_id": job.id,
      "artefacts": artefacts,
      "bom": None,
      "params": (job.metrics or {}).get('params'),
      "notes": None,
    }


