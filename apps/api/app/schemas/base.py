from typing import Any

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
    id: int | None = None
    email: str
    role: str = "engineer"
    locale: str = "tr"


class FreeCADDetectResponse(BaseModel):
    found: bool
    path: str | None = None
    version: str | None = None
    asm4_available: bool | None = None
    message: str | None = None


class JobMetrics(BaseModel):
    elapsed_ms: int
    file_size: int | None = None
    object_count: int | None = None
    freecad_version: str | None = None


class ArtefactInfo(BaseModel):
    path: str | None = None
    s3_key: str | None = None


class JobResult(BaseModel):
    success: bool
    message: str
    metrics: JobMetrics
    artefact: ArtefactInfo


