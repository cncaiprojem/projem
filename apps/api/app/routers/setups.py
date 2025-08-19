# LEGACY ROUTER - DISABLED
# This router uses legacy Setup/Project models not in Task Master ERD
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from typing import Optional

from ..db import db_session
from ..models_project import Project, Setup
from ..schemas.m18 import SetupCreate, SetupOut, Op3DPlan
from ..services.job_control import is_queue_paused
from ..security.oidc import require_role
from ..settings import app_settings as appset
from ..repos.m18 import add_ops3d
from ..tasks.m18_cam import setup_cam_task_run
from ..tasks.m18_sim import setup_sim_task
from ..tasks.m18_post import setup_post_task

router = APIRouter(prefix="/api/v1/setups", tags=["m18-setups"])
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/legacy-disabled", tags=["Disabled"])

# All legacy setup functionality disabled - not part of Task Master ERD

"""
@router.post("", response_model=SetupOut, status_code=201, dependencies=[Depends(require_role(ROLE_OPERATOR_OR_VIEWER))])
def create_setup(payload: SetupCreate, idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key")):
    if appset.require_idempotency and not idempotency_key:
        raise HTTPException(status_code=400, detail="Idempotency-Key zorunlu")
    with db_session() as s:
        p = s.get(Project, payload.project_id)
        if not p:
            raise HTTPException(status_code=404, detail="Proje yok")
        st = Setup(
            project_id=payload.project_id,
            name=payload.name,
            wcs=payload.wcs,
            orientation_rx_deg=payload.orientation_rx_deg,
            orientation_ry_deg=payload.orientation_ry_deg,
            orientation_rz_deg=payload.orientation_rz_deg,
            status="draft",
        )
        s.add(st)
        s.flush()
        s.commit()
        return SetupOut(
            id=st.id,
            project_id=st.project_id,
            name=st.name,
            wcs=st.wcs,
            status=st.status,
            orientation_rx_deg=st.orientation_rx_deg,
            orientation_ry_deg=st.orientation_ry_deg,
            orientation_rz_deg=st.orientation_rz_deg,
        )


@router.post("/{setup_id}/plan-ops3d", status_code=202, dependencies=[Depends(require_role(ROLE_OPERATOR_OR_VIEWER))])
def plan_ops3d(setup_id: int, payload: Op3DPlan):
    if not payload.ops:
        raise HTTPException(status_code=422, detail="ops boş olamaz")
    with db_session() as s:
        st = s.get(Setup, setup_id)
        if not st:
            raise HTTPException(status_code=404, detail="setup bulunamadı")
        count = add_ops3d(s, setup_id, payload.ops)
        return {"accepted": True, "count": count}


@router.post("/{setup_id}/cam", status_code=202, dependencies=[Depends(require_role(ROLE_OPERATOR_OR_VIEWER))])
def enqueue_cam(setup_id: int):
    if is_queue_paused("freecad"):
        raise HTTPException(status_code=409, detail="Kuyruk duraklatılmış")
    # V2: doğrudan run (sync) veya Celery cam.generate üzerinden
    # Prod: Celery'e at. Dev: senkron çalıştırma flag ile kontrol edilir
    try:
        from ..tasks.cam_build import cam_build_task  # type: ignore
        cam_build_task.apply_async(args=[setup_id], queue="freecad")
        return {"accepted": True}
    except Exception:
        # Senkron fallback (yalnız dev/demo)
        try:
            setup_cam_task_run(setup_id)
            return {"accepted": True, "mode": "sync-fallback"}
        except Exception:
            raise HTTPException(status_code=503, detail="Kuyruğa alınamadı")


@router.post("/{setup_id}/simulate", status_code=202, dependencies=[Depends(require_role(ROLE_OPERATOR_OR_VIEWER))])
def enqueue_sim(setup_id: int):
    if is_queue_paused("sim"):
        raise HTTPException(status_code=409, detail="Kuyruk duraklatılmış")
    try:
        setup_sim_task.apply_async(args=[setup_id], queue="sim")
    except Exception:
        raise HTTPException(status_code=503, detail="Kuyruğa alınamadı")
    return {"accepted": True}


@router.post("/{setup_id}/post", status_code=202, dependencies=[Depends(require_role(ROLE_OPERATOR_OR_VIEWER))])
def enqueue_post(setup_id: int):
    if is_queue_paused("postproc"):
        raise HTTPException(status_code=409, detail="Kuyruk duraklatılmış")
    with db_session() as s:
        st = s.get(Setup, setup_id)
        if not st:
            raise HTTPException(status_code=404, detail="setup bulunamadı")
        if st.status != "sim_ok":
            raise HTTPException(status_code=409, detail="Sim OK olmadan post yasak")
    try:
        setup_post_task.apply_async(args=[setup_id], queue="postproc")
    except Exception:
        raise HTTPException(status_code=503, detail="Kuyruğa alınamadı")
    return {"accepted": True}


@router.get("/project/{project_id}", dependencies=[Depends(require_role(ROLE_OPERATOR_OR_VIEWER))])
def list_setups(project_id: int):
    with db_session() as s:
        rows = s.query(Setup).filter(Setup.project_id == project_id).order_by(Setup.id.asc()).all()
        items = [
            SetupOut(
                id=r.id,
                project_id=r.project_id,
                name=r.name,
                wcs=r.wcs,
                status=r.status,  # type: ignore[arg-type]
                orientation_rx_deg=r.orientation_rx_deg,
                orientation_ry_deg=r.orientation_ry_deg,
                orientation_rz_deg=r.orientation_rz_deg,
            )
            for r in rows
        ]
        return {"items": [i.model_dump() for i in items]}
"""
