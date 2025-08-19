from __future__ import annotations

import tempfile
from pathlib import Path

from celery import shared_task

from ..db import db_session
from ..models_tooling import ShopPackage
from ..reports.shop_package import build_shop_package_pdf
from ..storage import upload_and_sign


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
    acks_late=True,
    queue="cpu",
)
def shop_package_task(self, project_id: int):
    with tempfile.TemporaryDirectory() as td:
        pdf_local = Path(td) / f"shop_package_{project_id}.pdf"
        meta = build_shop_package_pdf(project_id, str(pdf_local))
        art = upload_and_sign(pdf_local, "report/pdf")
        with db_session() as s:
            sp = ShopPackage(
                project_id=project_id,
                pdf_path=art["s3_key"],
                pdf_sha256=meta["sha256"],
            )
            s.add(sp)
            s.commit()
        return {"project_id": project_id, "pages": meta["pages"], "url": art.get("signed_url")}
