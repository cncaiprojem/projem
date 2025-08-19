# LEGACY ROUTER - DISABLED
# This router uses legacy Fixture model not in Task Master ERD
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from ..db import db_session
from ..schemas.m18 import FixtureCreate, FixtureOut
from ..security.oidc import require_role
from ..settings import app_settings as appset
from ..models_project import Fixture


router = APIRouter(prefix="/api/v1/fixtures", tags=["m18-fixtures"])
ROLE_ADMIN_OR_VIEWER = "admin" if appset.oidc_enabled else "viewer"


@router.post("", response_model=FixtureOut, status_code=201, dependencies=[Depends(require_role(ROLE_ADMIN_OR_VIEWER))])
def create_fixture(payload: FixtureCreate):
    with db_session() as s:
        fx = Fixture(name=payload.name, type=payload.type, safety_clear_mm=payload.safety_clear_mm)
        s.add(fx)
        s.flush()
        s.commit()
        return FixtureOut(id=fx.id, name=fx.name, type=fx.type, safety_clear_mm=fx.safety_clear_mm)


@router.get("", dependencies=[Depends(require_role("viewer"))])
def list_fixtures():
    with db_session() as s:
        rows = s.query(Fixture).order_by(Fixture.id.desc()).limit(100).all()
        return {"items": [FixtureOut(id=r.id, name=r.name, type=r.type, safety_clear_mm=r.safety_clear_mm) for r in rows]}
"""

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/legacy-disabled", tags=["Disabled"])


