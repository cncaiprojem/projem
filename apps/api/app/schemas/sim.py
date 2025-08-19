from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .cad import ArtefactRef


class SimJobCreate(BaseModel):
    assembly_job_id: int
    gcode_job_id: int | None = None
    resolution_mm: float = Field(0.8, gt=0)
    method: Literal["voxel", "occ-high"] = "voxel"
    bounds: dict | None = None  # {"x":[0,300],"y":[0,300],"z":[-50,150]}


class SimJobResult(BaseModel):
    status: Literal["pending", "running", "succeeded", "failed"]
    artefacts: list[ArtefactRef] = []
    metrics: dict = {}
    error_message: str | None = None


