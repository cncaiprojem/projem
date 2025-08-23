"""
Job status response schemas for Task 6.5.

Ultra enterprise-grade job status API with queue position tracking.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict

from ..models.enums import JobStatus, JobType


class JobProgressResponse(BaseModel):
    """Job progress information."""
    
    percent: int = Field(
        ...,
        ge=0,
        le=100,
        description="Progress percentage (0-100)"
    )
    step: Optional[str] = Field(
        None,
        description="Current processing step name"
    )
    message: Optional[str] = Field(
        None,
        description="Human-readable progress message"
    )
    updated_at: Optional[datetime] = Field(
        None,
        description="Last progress update timestamp"
    )
    
    model_config = ConfigDict(from_attributes=True)


class JobErrorResponse(BaseModel):
    """Job error information."""
    
    code: str = Field(
        ...,
        description="Error code for categorization"
    )
    message: str = Field(
        ...,
        description="Human-readable error message"
    )
    
    model_config = ConfigDict(from_attributes=True)


class ArtefactResponse(BaseModel):
    """Artefact information in job response."""
    
    id: int = Field(
        ...,
        description="Artefact unique identifier"
    )
    type: str = Field(
        ...,
        description="Artefact type (model, gcode, report, etc.)"
    )
    s3_key: str = Field(
        ...,
        description="S3 object key for the artefact"
    )
    sha256: str = Field(
        ...,
        description="SHA-256 hash for integrity verification"
    )
    size: int = Field(
        ...,
        description="File size in bytes"
    )
    
    model_config = ConfigDict(from_attributes=True)


class JobStatusResponse(BaseModel):
    """
    Complete job status response for Task 6.5.
    
    Includes all job details, progress, artefacts, and queue position.
    """
    
    id: int = Field(
        ...,
        description="Job unique identifier"
    )
    type: JobType = Field(
        ...,
        description="Job type (freecad_model, freecad_cam, etc.)"
    )
    status: JobStatus = Field(
        ...,
        description="Current job status"
    )
    progress: JobProgressResponse = Field(
        ...,
        description="Job progress information"
    )
    attempts: int = Field(
        ...,
        ge=0,
        description="Number of execution attempts"
    )
    cancel_requested: bool = Field(
        ...,
        description="Whether cancellation has been requested"
    )
    created_at: datetime = Field(
        ...,
        description="Job creation timestamp"
    )
    updated_at: datetime = Field(
        ...,
        description="Last update timestamp"
    )
    artefacts: List[ArtefactResponse] = Field(
        default_factory=list,
        description="List of generated artefacts"
    )
    last_error: Optional[JobErrorResponse] = Field(
        None,
        description="Last error information if failed"
    )
    queue_position: Optional[int] = Field(
        None,
        ge=0,
        description="Estimated position in the queue (0 means currently processing, None if completed/failed)"
    )
    
    # Optional fields for completed jobs
    started_at: Optional[datetime] = Field(
        None,
        description="Job execution start timestamp"
    )
    finished_at: Optional[datetime] = Field(
        None,
        description="Job completion timestamp"
    )
    
    model_config = ConfigDict(from_attributes=True)