from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

WcsName = Literal["G54", "G55", "G56", "G57", "G58", "G59"]


class StockSpec(BaseModel):
    shape: Literal["block", "cylinder"] = "block"
    x_mm: float = 100
    y_mm: float = 70
    z_mm: float = 10


class CamBuildRequest(BaseModel):
    project_id: int
    machine_post: Optional[str] = None
    wcs: WcsName = "G54"
    stock: StockSpec = Field(default_factory=StockSpec)
    strategy: Literal["balanced", "fast", "safe"] = "balanced"
    fast_mode: bool = False


class CamOpSummary(BaseModel):
    name: str
    type: str
    est_seconds: float


class CamBuildArtifacts(BaseModel):
    fcstd_url: Optional[str] = None
    job_json_url: Optional[str] = None
    svg_url: Optional[str] = None


class CamBuildOut(BaseModel):
    job_id: str
    message: str = "CAM işi kuyruğa alındı"


class CamArtifactsOut(BaseModel):
    artifacts: CamBuildArtifacts
    ops: List[CamOpSummary] = []
    job_stats: Dict[str, Any] = {}
