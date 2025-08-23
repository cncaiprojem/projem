# -*- coding: utf-8 -*-
"""
Job creation schemas for Task 6.4.
İş oluşturma şemaları.
"""

from typing import Any, Dict, Optional
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field, validator

from ..models.enums import JobType


class JobCreateRequest(BaseModel):
    """
    İş oluşturma isteği.
    Request schema for creating a new job.
    """
    
    type: JobType = Field(
        ...,
        description="Job type (ai, model, cam, sim, report, erp)"
    )
    
    params: Dict[str, Any] = Field(
        ...,
        description="Job-specific parameters"
    )
    
    idempotency_key: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Unique key for idempotent requests"
    )
    
    priority: Optional[int] = Field(
        default=0,
        ge=-100,
        le=100,
        description="Job priority (-100 to 100, higher = more priority)"
    )
    
    @validator('idempotency_key')
    def validate_idempotency_key(cls, v: str) -> str:
        """Ensure idempotency key is not empty or whitespace."""
        v = v.strip()
        if not v:
            raise ValueError("Idempotency key cannot be empty or whitespace")
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "type": "model",
                "params": {
                    "model_type": "parametric",
                    "dimensions": {"x": 100, "y": 50, "z": 25}
                },
                "idempotency_key": "model-123-v1",
                "priority": 10
            }
        }


class JobCreateResponse(BaseModel):
    """
    İş oluşturma yanıtı.
    Response schema for job creation.
    """
    
    id: int = Field(..., description="Job ID")
    
    type: JobType = Field(..., description="Job type")
    
    status: str = Field(..., description="Job status")
    
    idempotency_key: str = Field(..., description="Idempotency key")
    
    created_at: datetime = Field(..., description="Creation timestamp")
    
    task_id: Optional[str] = Field(None, description="Celery task ID")
    
    queue: str = Field(..., description="Target queue name")
    
    message: str = Field(..., description="Status message")
    
    is_duplicate: bool = Field(
        default=False,
        description="True if this was an idempotent hit"
    )
    
    class Config:
        orm_mode = True
        schema_extra = {
            "example": {
                "id": 123,
                "type": "model",
                "status": "pending",
                "idempotency_key": "model-123-v1",
                "created_at": "2025-08-23T10:00:00Z",
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "queue": "model",
                "message": "Job created and queued successfully",
                "is_duplicate": False
            }
        }


class JobErrorResponse(BaseModel):
    """
    İş hatası yanıtı.
    Error response for job operations.
    """
    
    error: str = Field(..., description="Error code")
    
    message: str = Field(..., description="Error message")
    
    details: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional error details"
    )
    
    retryable: bool = Field(
        default=False,
        description="Whether the error is retryable"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "error": "ERR-JOB-422",
                "message": "Job payload validation failed",
                "details": {
                    "validation_errors": [
                        {
                            "field": "params.model_type",
                            "message": "field required",
                            "type": "value_error.missing"
                        }
                    ]
                },
                "retryable": False
            }
        }


class RateLimitErrorResponse(BaseModel):
    """
    Hız sınırı hatası yanıtı.
    Rate limit error response.
    """
    
    error: str = Field(
        default="ERR-JOB-RATE-LIMIT",
        description="Error code"
    )
    
    message: str = Field(..., description="Error message")
    
    remaining: int = Field(..., description="Remaining requests")
    
    reset_in: int = Field(..., description="Seconds until reset")
    
    limit: int = Field(..., description="Rate limit maximum")
    
    class Config:
        schema_extra = {
            "example": {
                "error": "ERR-JOB-RATE-LIMIT",
                "message": "Rate limit exceeded. Please try again later.",
                "remaining": 0,
                "reset_in": 45,
                "limit": 60
            }
        }


__all__ = [
    "JobCreateRequest",
    "JobCreateResponse",
    "JobErrorResponse",
    "RateLimitErrorResponse",
]