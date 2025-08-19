from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, Dict

from celery import shared_task

from ..db import db_session
from ..models_project import Project, ProjectFile, FileKind, ProjectStatus
from ..storage import upload_and_sign, get_s3_client, presigned_url
from ..freecad.service import detect_freecad
from ..freecad.path_build import build_cam_job
from ..cam.cam_plan import derive_cam_params


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
    queue="cpu",
)
def cam_build_task(
    self,
    project_id: int,
    machine_post: str | None,
    wcs: str,
    stock: Dict[str, Any],
    strategy: str = "balanced",
):
    # Plan ve FCStd artefaktını hazırla
    with db_session() as s:
        p = s.get(Project, project_id)
        if not p:
            raise RuntimeError("Proje bulunamadı.")
        plan = (p.summary_json or {}).get("plan") or {}
        # FCStd dosyasını ProjectFile'lerden bul
        fcstd_file: ProjectFile | None = (
            s.query(ProjectFile)
            .filter(ProjectFile.project_id == project_id, ProjectFile.kind == FileKind.cad)
            .order_by(ProjectFile.created_at.desc())
            .first()
        )
        if (
            not fcstd_file
            or not fcstd_file.s3_key
            or not fcstd_file.s3_key.lower().endswith(".fcstd")
        ):
            raise RuntimeError("FCStd artefaktı bulunamadı.")
        s3_key = fcstd_file.s3_key

    # İndirilecek lokal path
    tmp_root = tempfile.mkdtemp(prefix="cam_")
    fcstd_local = Path(tmp_root) / "model.fcstd"

    # S3'ten indir (presigned varsa kullan, yoksa doğrudan S3 client)
    url = presigned_url(s3_key)
    if url:
        # Güvenli indirme (boyut/hash kontrol)
        from ..storage_download import download_presigned

        download_presigned(url, str(fcstd_local))
    else:
        s3 = get_s3_client()
        s3.download_file("artefacts", s3_key, str(fcstd_local))

    # FreeCADCmd hazır mı
    fc = detect_freecad()
    if not fc.found or not fc.path:
        raise RuntimeError("FreeCADCmd bulunamadı")

    # CAM paramları türet
    cam = derive_cam_params(plan, strategy=strategy)

    # CAM job'u oluştur
    tmp_build = Path(tmp_root) / "build"
    tmp_build.mkdir(parents=True, exist_ok=True)

    out = build_cam_job(
        str(fcstd_local),
        cam=cam,
        stock=stock,
        wcs=wcs,
        post_name=machine_post,
        tmpdir=str(tmp_build),
        db=None,
    )

    # Güncellenen FCStd ve özet JSON'u yükle
    fcstd_art = upload_and_sign(fcstd_local, "cam/fcstd")
    job_json_path = Path(out["job_json"]) if out.get("job_json") else None
    job_json_art = None
    if job_json_path and job_json_path.exists():
        job_json_art = upload_and_sign(job_json_path, "cam/job_json")

    svg_art = None
    svg_path = out.get("svg")
    if svg_path:
        sp = Path(svg_path)
        if sp.exists():
            svg_art = upload_and_sign(sp, "cam/job_svg")

    # DB güncelle
    with db_session() as s:
        p = s.get(Project, project_id)
        arts = {
            "fcstd_url": fcstd_art.get("signed_url"),
            "job_json_url": (job_json_art or {}).get("signed_url"),
            "svg_url": (svg_art or {}).get("signed_url"),
        }
        p.status = ProjectStatus.cam_ready
        prev = p.summary_json or {}
        prev["cam_artifacts"] = arts
        prev["cam_job"] = {"ops": out.get("ops", []), "wcs": wcs, "stock": stock}
        p.summary_json = prev
        s.commit()

    return {
        "project_id": project_id,
        "artifacts": arts,
        "ops": out.get("ops", []),
    }
