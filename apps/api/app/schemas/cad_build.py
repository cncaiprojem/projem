from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class CadBuildRequest(BaseModel):
    project_id: int
    fast_mode: bool = False


class CadBuildResult(BaseModel):
    job_id: str
    message: str = "CAD üretimi kuyruğa alındı"


class CadArtifactsOut(BaseModel):
    fcstd_url: Optional[str] = None
    step_url: Optional[str] = None
    stl_url: Optional[str] = None
    gltf_url: Optional[str] = None
    stats: Dict[str, Any] = Field(default_factory=dict)
