from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from ..db import db_session
from ..llm_router import analyze_and_plan, refine_plan
from ..models_project import Project, ProjectStatus
from ..schemas.project import DesignAnswerIn, DesignAnswerOut, DesignPlanIn, DesignPlanOut

router = APIRouter(prefix="/api/v1/design", tags=["Tasarım Planı"])


@router.post("/plan", response_model=DesignPlanOut)
def design_plan(payload: DesignPlanIn, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    with db_session() as s:
        p = s.get(Project, payload.project_id)
        if not p:
            raise HTTPException(status_code=404, detail="Proje bulunamadı.")
        try:
            plan = analyze_and_plan(prompt=payload.prompt, context=payload.context or {})
        except Exception as e:
            # LLM yapılandırılmadıysa kontrollü hata döndür
            raise HTTPException(status_code=503, detail=f"Plan üretilemedi: {e}")
        p.status = ProjectStatus.planning
        p.summary_json = plan
        s.commit()
        return plan


@router.post("/answer", response_model=DesignAnswerOut)
def design_answer(payload: DesignAnswerIn):
    with db_session() as s:
        p = s.get(Project, payload.project_id)
        if not p:
            raise HTTPException(status_code=404, detail="Proje bulunamadı.")
        new_plan = refine_plan(current=p.summary_json or {}, answers=payload.answers)
        p.summary_json = new_plan
        s.commit()
        return new_plan


