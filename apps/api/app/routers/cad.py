from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from ..db import db_session
from ..schemas.cad_build import CadBuildRequest, CadBuildResult, CadArtifactsOut
from ..tasks.cad import cad_build_task

# from ..models_project import Project  # Module not found
from ..schemas.cam_build import (
    CamBuildRequest,
    CamBuildOut,
    CamArtifactsOut as CamArtifactsOut2,
    CamBuildArtifacts,
    CamOpSummary,
)
from ..tasks.cam_build import cam_build_task  # noqa: F401
from ..config import settings


def _broker_ok() -> bool:
    try:
        import redis  # type: ignore

        r = redis.Redis.from_url(settings.redis_url)
        return bool(r.ping())
    except Exception:
        return False


router = APIRouter(prefix="/api/v1/cad", tags=["CAD"])


@router.post("/build", response_model=CadBuildResult)
def cad_build(payload: CadBuildRequest):
    with db_session() as s:
        p = s.get(Project, payload.project_id)
        if not p:
            raise HTTPException(status_code=404, detail="Proje yok.")
    if not _broker_ok():
        raise HTTPException(
            status_code=503, detail="Kuyruk servisi (Redis) erişilemiyor. Lütfen tekrar deneyin."
        )
    res = cad_build_task.delay(payload.project_id)
    return CadBuildResult(job_id=res.id)


@router.get("/artifacts/{project_id}", response_model=CadArtifactsOut)
def cad_artifacts(project_id: int):
    with db_session() as s:
        p = s.get(Project, project_id)
        if not p or not p.summary_json:
            raise HTTPException(status_code=404, detail="Proje yok.")
        arts = (p.summary_json or {}).get("cad_artifacts") or {}
        stats = (p.summary_json or {}).get("cad_stats") or {}
        return CadArtifactsOut(
            fcstd_url=arts.get("fcstd"),
            step_url=arts.get("step"),
            stl_url=arts.get("stl"),
            gltf_url=arts.get("gltf"),
            stats=stats,
        )


cam2 = APIRouter(prefix="/api/v1/cam2", tags=["cam"])


@cam2.post("/build", response_model=CamBuildOut)
def cam_build(
    payload: CamBuildRequest, idem: str | None = Header(default=None, alias="Idempotency-Key")
):
    with db_session() as s:
        p = s.get(Project, payload.project_id)
        if not p:
            raise HTTPException(status_code=404, detail="Proje yok.")
    r = cam_build_task.delay(
        payload.project_id,
        payload.machine_post,
        payload.wcs,
        payload.stock.model_dump(),
        payload.strategy,
    )
    return CamBuildOut(job_id=r.id)


@cam2.get("/artifacts/{project_id}", response_model=CamArtifactsOut2)
def cam_artifacts2(project_id: int):
    with db_session() as s:
        p = s.get(Project, project_id)
        if not p:
            raise HTTPException(status_code=404, detail="Proje yok.")
        summ = p.summary_json or {}
        arts = summ.get("cam_artifacts") or {}
        ops = [CamOpSummary(**o) for o in (summ.get("cam_job", {}).get("ops") or [])]
        stats = {
            "wcs": (summ.get("cam_job", {}).get("wcs")),
            "stock": summ.get("cam_job", {}).get("stock"),
        }
        return CamArtifactsOut2(
            artifacts=CamBuildArtifacts(
                fcstd_url=arts.get("fcstd_url"),
                job_json_url=arts.get("job_json_url"),
                svg_url=arts.get("svg_url"),
            ),
            ops=ops,
            job_stats=stats,
        )
