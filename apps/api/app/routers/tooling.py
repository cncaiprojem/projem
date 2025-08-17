# LEGACY ROUTER - DISABLED  
# This router uses legacy Tool/ToolPreset models not in Task Master ERD
# Use the new Tool model from Task Master ERD instead
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Optional

from ..db import db_session
from ..models_tooling import Tool, ToolPreset
from ..tooling.scan import scan_toolbits
from ..config import settings


router = APIRouter(prefix="/api/v1", tags=["tooling"])
"""

from fastapi import APIRouter  
router = APIRouter(prefix="/api/v1/legacy-disabled", tags=["Disabled"])

# All legacy tooling endpoints disabled
"""
@router.get("/tools")
def list_tools(type: Optional[str] = None, dia: Optional[float] = None):
    with db_session() as s:
        q = s.query(Tool)
        if type:
            q = q.filter(Tool.type == type)
        if dia is not None:
            q = q.filter(Tool.diameter_mm == dia)
        return [
            {"id": t.id, "name": t.name, "type": t.type, "diameter_mm": t.diameter_mm}
            for t in q.order_by(Tool.type, Tool.diameter_mm).all()
        ]


@router.post("/tools/scan")
def scan():
    root = settings.toolbits_root or "/data/toolbits"
    items = scan_toolbits(root)
    return {"count": len(items), "items": items}
"""


