from datetime import datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, Field


class HealthStatus(BaseModel):
    status: str
    dependencies: dict[str, Any]


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="Erişim token süresi (saniye)")


class UserOut(BaseModel):
    id: Optional[int] = None
    email: str
    role: str = "engineer"
    locale: str = "tr"


class FreeCADDetectResponse(BaseModel):
    found: bool
    path: Optional[str] = None
    version: Optional[str] = None
    asm4_available: Optional[bool] = None
    message: Optional[str] = None


class JobMetrics(BaseModel):
    elapsed_ms: int
    file_size: Optional[int] = None
    object_count: Optional[int] = None
    freecad_version: Optional[str] = None


class ArtefactInfo(BaseModel):
    path: Optional[str] = None
    s3_key: Optional[str] = None


class JobResult(BaseModel):
    success: bool
    message: str
    metrics: JobMetrics
    artefact: ArtefactInfo
