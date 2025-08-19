from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .cad import ArtefactRef


class SimJobCreate(BaseModel):
    assembly_job_id: int
    gcode_job_id: Optional[int] = None
    resolution_mm: float = Field(0.8, gt=0)
    method: Literal["voxel", "occ-high"] = "voxel"
    bounds: Optional[dict] = None  # {"x":[0,300],"y":[0,300],"z":[-50,150]}


class SimJobResult(BaseModel):
    status: Literal["pending", "running", "succeeded", "failed"]
    artefacts: List[ArtefactRef] = []
    metrics: dict = {}
    error_message: Optional[str] = None
