from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Depends

from ..services import dlq


from ..security.oidc import require_role


router = APIRouter(prefix="/api/v1/admin/dlq", tags=["DLQ Yönetimi"])


@router.get("", dependencies=[Depends(require_role("admin"))])
def list_dead(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return {"items": dlq.list_dead(limit=limit, offset=offset), "limit": limit, "offset": offset}


@router.post("/{job_id}/requeue", dependencies=[Depends(require_role("admin"))])
def requeue(job_id: int):
    ok = dlq.requeue(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="İş yeniden sıraya alınamadı")
    return {"status": "requeued", "job_id": job_id}
