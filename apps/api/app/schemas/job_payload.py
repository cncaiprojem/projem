"""
Pydantic schemas for job payload validation - Task 6.3.
İş yükü doğrulama için Pydantic şemaları.

Task 6.3 Canonical payload structure:
{
    job_id: uuid,
    type: enum,
    params: object,
    submitted_by: user_id,
    attempt: int,
    created_at: iso8601
}
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Type, Union
from uuid import UUID
import json

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.functional_validators import AfterValidator
from typing_extensions import Annotated

from ..core.job_routing import JobType


# Maximum payload size in bytes (256KB per Task 6.3)
MAX_PAYLOAD_SIZE_BYTES = 256 * 1024  # 256KB


class BaseJobParams(BaseModel):
    """
    Temel iş parametreleri - tüm iş türleri için ortak alanlar.
    Base job parameters - common fields for all job types.
    """
    
    # Large artifacts should be referenced via object storage keys
    # Büyük dosyalar object storage anahtarları ile referans edilmeli
    file_keys: Optional[List[str]] = Field(
        default=None,
        description="Object storage keys for large artifacts (S3/MinIO)",
        max_length=10,
    )
    
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata for the job",
    )
    
    class Config:
        extra = "forbid"  # Reject unknown fields


class AIJobParams(BaseJobParams):
    """AI/ML job specific parameters."""
    
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="AI prompt or instruction",
    )
    
    ai_model_config: Optional[Dict[str, Any]] = Field(
        default=None,
        description="AI model configuration",
    )


class ModelJobParams(BaseJobParams):
    """3D model generation job parameters."""
    
    model_type: str = Field(
        ...,
        description="Type of 3D model to generate",
    )
    
    dimensions: Dict[str, float] = Field(
        ...,
        description="Model dimensions (x, y, z)",
    )
    
    parameters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Model-specific parameters",
    )


class CAMJobParams(BaseJobParams):
    """CAM path generation job parameters."""
    
    model_key: str = Field(
        ...,
        description="Object storage key for input model",
    )
    
    tool_config: Dict[str, Any] = Field(
        ...,
        description="Tool configuration for CAM",
    )
    
    strategy: str = Field(
        ...,
        description="CAM strategy to use",
    )


class SimJobParams(BaseJobParams):
    """Simulation job parameters."""
    
    simulation_type: str = Field(
        ...,
        description="Type of simulation to run",
    )
    
    model_key: str = Field(
        ...,
        description="Object storage key for model",
    )
    
    simulation_params: Dict[str, Any] = Field(
        ...,
        description="Simulation-specific parameters",
    )


class ReportJobParams(BaseJobParams):
    """Report generation job parameters."""
    
    report_type: str = Field(
        ...,
        description="Type of report to generate",
    )
    
    data_keys: List[str] = Field(
        ...,
        description="Object storage keys for report data",
        min_length=1,
        max_length=50,
    )
    
    format: str = Field(
        default="pdf",
        description="Report output format",
        pattern="^(pdf|html|xlsx|docx)$",
    )


class ERPJobParams(BaseJobParams):
    """ERP integration job parameters."""
    
    operation: str = Field(
        ...,
        description="ERP operation type",
    )
    
    entity_type: str = Field(
        ...,
        description="ERP entity type",
    )
    
    data: Dict[str, Any] = Field(
        ...,
        description="ERP data payload",
    )


# Type mapping for job parameters
JOB_PARAMS_MAPPING: Dict[JobType, Type[BaseJobParams]] = {
    JobType.AI: AIJobParams,
    JobType.MODEL: ModelJobParams,
    JobType.CAM: CAMJobParams,
    JobType.SIM: SimJobParams,
    JobType.REPORT: ReportJobParams,
    JobType.ERP: ERPJobParams,
}


class TaskPayload(BaseModel):
    """
    Canonical task payload schema - Task 6.3 specification.
    Kanonik görev yükü şeması.
    """
    
    job_id: UUID = Field(
        ...,
        description="Unique job identifier",
    )
    
    type: JobType = Field(
        ...,
        description="Job type enumeration",
    )
    
    params: Dict[str, Any] = Field(
        ...,
        description="Job-specific parameters",
    )
    
    submitted_by: int = Field(
        ...,
        description="User ID who submitted the job",
        gt=0,
    )
    
    attempt: int = Field(
        default=1,
        description="Attempt number for retry tracking",
        ge=1,
        le=10,  # Max 10 attempts
    )
    
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Job creation timestamp (ISO 8601)",
    )
    
    @field_validator("params")
    @classmethod
    def validate_params_not_empty(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        """Params dictionary must not be empty."""
        if not v:
            raise ValueError("params cannot be empty")
        return v
    
    @model_validator(mode="after")
    def validate_params_for_job_type(self) -> "TaskPayload":
        """
        İş türüne göre parametreleri doğrula.
        Validate params based on job type.
        """
        params_class = JOB_PARAMS_MAPPING.get(self.type)
        if not params_class:
            raise ValueError(f"Unknown job type: {self.type}")
        
        try:
            # Validate params against the appropriate schema
            validated_params = params_class(**self.params)
            # Convert back to dict for storage
            self.params = validated_params.model_dump(exclude_unset=True)
        except Exception as e:
            raise ValueError(f"Invalid params for job type {self.type}: {str(e)}")
        
        return self
    
    @model_validator(mode="after")
    def validate_payload_size(self) -> "TaskPayload":
        """
        Yük boyutunu kontrol et - maksimum 256KB.
        Validate payload size - maximum 256KB.
        """
        # Serialize to JSON to check size
        try:
            payload_json = self.model_dump_json()
        except (TypeError, ValueError) as e:
            raise ValueError(f"Failed to serialize payload to JSON: {e}") from e
        payload_size = len(payload_json.encode("utf-8"))
        
        if payload_size > MAX_PAYLOAD_SIZE_BYTES:
            raise ValueError(
                f"Payload size ({payload_size} bytes) exceeds maximum "
                f"allowed size ({MAX_PAYLOAD_SIZE_BYTES} bytes). "
                "Large artifacts should be stored in object storage and referenced via keys."
            )
        
        return self
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        }
        json_schema_extra = {
            "example": {
                "job_id": "550e8400-e29b-41d4-a716-446655440000",
                "type": "model",
                "params": {
                    "model_type": "parametric",
                    "dimensions": {"x": 100.0, "y": 50.0, "z": 25.0},
                    "file_keys": ["models/input/base.fcstd"],
                },
                "submitted_by": 1,
                "attempt": 1,
                "created_at": "2025-01-22T10:30:00Z",
            }
        }


class TaskPayloadResponse(BaseModel):
    """
    Response model for task payload submission.
    Görev yükü gönderimi için yanıt modeli.
    """
    
    job_id: UUID
    status: str = Field(default="queued")
    queue: str
    routing_key: str
    message: str = Field(default="Task successfully queued")
    
    class Config:
        json_encoders = {
            UUID: lambda v: str(v),
        }


# Export all public symbols
__all__ = [
    "BaseJobParams",
    "AIJobParams",
    "ModelJobParams",
    "CAMJobParams",
    "SimJobParams",
    "ReportJobParams",
    "ERPJobParams",
    "TaskPayload",
    "TaskPayloadResponse",
    "JOB_PARAMS_MAPPING",
    "MAX_PAYLOAD_SIZE_BYTES",
]