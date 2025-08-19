from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException

from ..audit import audit
from ..security.oidc import Principal, require_role

router = APIRouter(prefix="/api/v1/admin", tags=["PII Yönetimi"])


@router.post("/unmask-preview", dependencies=[Depends(require_role("admin"))])
def unmask_preview(payload: dict = Body(...), reason: str = Body(..., embed=True), principal: Principal = Depends(require_role("admin"))):
    if not reason or len(reason.strip()) < 5:
        raise HTTPException(status_code=422, detail="Gerekçe en az 5 karakter olmalıdır")
    # Audit'e yaz (unmasked_by, reason)
    audit("pii.unmask", reason=reason, unmasked_by=principal.sub)
    # Sadece önizleme: payload'ı aynen döndür, log'a yazma
    return {"preview": payload}


