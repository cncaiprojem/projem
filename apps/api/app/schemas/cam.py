from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .cad import ArtefactRef


class CamJobCreate(BaseModel):
    assembly_job_id: int
    post: Literal["grbl", "marlin", "fanuc"] = "grbl"
    tool_diameter_mm: float = Field(6.0, gt=0)
    spindle_rpm: int = Field(8000, gt=0)
    feed_mm_min: float = Field(600, gt=0)
    plunge_mm_min: float = Field(200, gt=0)
    stepdown_mm: float = Field(1.0, gt=0)
    safe_z_mm: float = Field(5.0)
    stock_margin_mm: float = Field(2.0, ge=0)
    units: Literal["mm", "inch"] = "mm"
    machine_bounds_mm: Optional[dict] = None  # {"x":[0,300],"y":[0,300],"z":[-50,150]}


class CamJobResult(BaseModel):
    status: Literal["pending", "running", "succeeded", "failed"]
    artefacts: List[ArtefactRef] = []
    metrics: dict = {}
    error_message: Optional[str] = None
