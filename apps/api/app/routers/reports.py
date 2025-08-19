from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..db import db_session
from ..models_tooling import ShopPackage
from ..tasks.reports import shop_package_task

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.post("/shop-package")
def create_shop_package(payload: dict):
    pid = int(payload.get("project_id"))
    res = shop_package_task.delay(pid)
    return {"job_id": res.id}


@router.get("/projects/{project_id}/shop-package")
def last_shop_package(project_id: int):
    with db_session() as s:
        sp = s.query(ShopPackage).filter(ShopPackage.project_id == project_id).order_by(ShopPackage.id.desc()).first()
        if not sp:
            raise HTTPException(status_code=404, detail="Paket bulunamadı")
        return {"s3_key": sp.pdf_path, "sha256": sp.pdf_sha256}


