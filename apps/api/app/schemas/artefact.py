"""
Artefact schemas for Task 5.7.

Implements Pydantic validation schemas for artefact persistence,
S3 tagging, and audit logging.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator, computed_field


class ArtefactType(str, Enum):
    """Artefact type enumeration."""
    MODEL = "model"
    GCODE = "gcode"
    REPORT = "report"
    INVOICE = "invoice"
    LOG = "log"
    SIMULATION = "simulation"
    ANALYSIS = "analysis"
    DRAWING = "drawing"
    TOOLPATH = "toolpath"
    OTHER = "other"


class ArtefactBase(BaseModel):
    """Base artefact schema."""
    
    job_id: int = Field(..., description="Associated job ID")
    type: ArtefactType = Field(..., description="Artefact type classification")
    s3_bucket: str = Field(..., max_length=255, description="S3 bucket name")
    s3_key: str = Field(..., max_length=1024, description="S3 object key")
    size_bytes: int = Field(..., gt=0, description="File size in bytes")
    sha256: str = Field(..., regex="^[a-fA-F0-9]{64}$", description="SHA256 hash")
    mime_type: str = Field(..., max_length=100, description="MIME type")
    machine_id: Optional[int] = Field(None, description="Optional machine ID")
    post_processor: Optional[str] = Field(None, max_length=100, description="Post-processor name")
    version_id: Optional[str] = Field(None, max_length=255, description="S3 version ID")
    meta: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    
    model_config = ConfigDict(use_enum_values=True)
    
    @field_validator('sha256')
    @classmethod
    def validate_sha256(cls, v: str) -> str:
        """Ensure SHA256 is lowercase."""
        return v.lower() if v else v


class ArtefactCreate(ArtefactBase):
    """Schema for creating an artefact."""
    
    created_by: int = Field(..., description="User ID who created the artefact")


class ArtefactUpdate(BaseModel):
    """Schema for updating an artefact."""
    
    machine_id: Optional[int] = None
    post_processor: Optional[str] = Field(None, max_length=100)
    meta: Optional[Dict[str, Any]] = None
    
    model_config = ConfigDict(use_enum_values=True)


class ArtefactResponse(ArtefactBase):
    """Schema for artefact response."""
    
    id: int
    created_by: int
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)
    
    # Computed properties using Pydantic v2 @computed_field
    @computed_field
    @property
    def size_mb(self) -> float:
        """Compute size in MB from bytes."""
        return self.size_bytes / (1024.0 * 1024.0)
    
    @computed_field
    @property
    def s3_full_path(self) -> str:
        """Full S3 path (bucket/key)."""
        return f"{self.s3_bucket}/{self.s3_key}"
    
    @computed_field
    @property
    def is_invoice(self) -> bool:
        """Whether artefact is an invoice."""
        return self.type == ArtefactType.INVOICE
    
    @computed_field
    @property
    def is_versioned(self) -> bool:
        """Whether artefact has version ID."""
        return bool(self.version_id)


class ArtefactListResponse(BaseModel):
    """Schema for listing artefacts."""
    
    items: List[ArtefactResponse]
    total: int
    page: int = 1
    per_page: int = 20
    has_next: bool = False
    has_prev: bool = False


class ArtefactTagRequest(BaseModel):
    """Schema for applying S3 tags to an artefact."""
    
    tags: Dict[str, str] = Field(..., description="Tags to apply")
    merge: bool = Field(True, description="Merge with existing tags")


class ArtefactRetentionRequest(BaseModel):
    """Schema for setting retention on an artefact."""
    
    retention_years: int = Field(10, ge=1, le=100, description="Retention period in years")
    legal_hold: bool = Field(False, description="Apply legal hold")
    compliance_mode: str = Field("COMPLIANCE", description="Retention mode")


class ArtefactDownloadResponse(BaseModel):
    """Schema for artefact download response."""
    
    download_url: str = Field(..., description="Presigned download URL")
    expires_in: int = Field(..., description="URL expiration in seconds")
    artefact_id: int = Field(..., description="Artefact ID")
    filename: str = Field(..., description="Original filename")
    size_bytes: int = Field(..., description="File size in bytes")
    mime_type: str = Field(..., description="MIME type")
    sha256: str = Field(..., description="SHA256 hash for verification")


class ArtefactS3TagsResponse(BaseModel):
    """Schema for S3 tags response."""
    
    artefact_id: int
    s3_bucket: str
    s3_key: str
    tags: Dict[str, str]
    version_id: Optional[str] = None


class ArtefactAuditEvent(BaseModel):
    """Schema for artefact audit events."""
    
    event_type: str = Field(..., description="Event type (upload, download, delete, etc.)")
    artefact_id: int = Field(..., description="Artefact ID")
    user_id: int = Field(..., description="User performing action")
    job_id: int = Field(..., description="Associated job ID")
    ip_address: Optional[str] = Field(None, description="Client IP address")
    user_agent: Optional[str] = Field(None, description="Client user agent")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional event details")


class ArtefactSearchParams(BaseModel):
    """Schema for searching artefacts."""
    
    job_id: Optional[int] = None
    type: Optional[ArtefactType] = None
    created_by: Optional[int] = None
    machine_id: Optional[int] = None
    post_processor: Optional[str] = None
    sha256: Optional[str] = None
    min_size_bytes: Optional[int] = None
    max_size_bytes: Optional[int] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None
    page: int = Field(1, ge=1)
    per_page: int = Field(20, ge=1, le=100)
    
    model_config = ConfigDict(use_enum_values=True)


class ArtefactStats(BaseModel):
    """Schema for artefact statistics."""
    
    total_count: int
    total_size_bytes: int
    total_size_gb: float
    by_type: Dict[str, int]
    by_user: Dict[int, int]
    by_machine: Dict[int, int]
    average_size_mb: float
    largest_size_mb: float
    
    model_config = ConfigDict(from_attributes=True)