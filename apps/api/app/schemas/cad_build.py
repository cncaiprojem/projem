from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CadBuildRequest(BaseModel):
    project_id: int
    fast_mode: bool = False


class CadBuildResult(BaseModel):
    job_id: str
    message: str = "CAD üretimi kuyruğa alındı"


class CadArtifactsOut(BaseModel):
    fcstd_url: str | None = None
    step_url: str | None = None
    stl_url: str | None = None
    gltf_url: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)


