from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

SetupStatus = Literal['draft','cam_ready','sim_ok','post_ok']


class SetupCreate(BaseModel):
    project_id: int
    name: str
    orientation_rx_deg: float = 0
    orientation_ry_deg: float = 0
    orientation_rz_deg: float = 0
    wcs: str = 'G54'
    fixture_id: int | None = None


class SetupOut(BaseModel):
    id: int
    project_id: int
    name: str
    wcs: str
    status: SetupStatus
    orientation_rx_deg: float
    orientation_ry_deg: float
    orientation_rz_deg: float


class Op3DPlan(BaseModel):
    ops: list[dict[str, Any]]


class FixtureCreate(BaseModel):
    name: str
    type: Literal['vise','plate','custom']
    safety_clear_mm: float = 10.0


class FixtureOut(BaseModel):
    id: int
    name: str
    type: str
    safety_clear_mm: float


