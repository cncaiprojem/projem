"""
Batch Processing Models for Enterprise CAD/CAM Operations

This module provides database models for batch processing of CAD models,
including quality checks, workflow automation, and batch job management.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from .base import Base, TimeStampedMixin


class BatchJobStatus(str, Enum):
    """Status values for batch processing jobs."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class BatchOperationType(str, Enum):
    """Types of batch operations."""
    QUALITY_CHECK = "quality_check"
    MESH_OPTIMIZATION = "mesh_optimization"
    FEATURE_CLEANUP = "feature_cleanup"
    MODEL_COMPRESSION = "model_compression"
    FORMAT_CONVERSION = "format_conversion"
    BATCH_EXPORT = "batch_export"
    BATCH_IMPORT = "batch_import"


class QualityCheckType(str, Enum):
    """Types of quality checks for CAD models."""
    GEOMETRY_VALIDATION = "geometry_validation"
    TOPOLOGY_CHECK = "topology_check"
    MESH_QUALITY = "mesh_quality"
    FEATURE_CONSISTENCY = "feature_consistency"
    DIMENSION_ACCURACY = "dimension_accuracy"
    MATERIAL_PROPERTIES = "material_properties"
    ASSEMBLY_CONSTRAINTS = "assembly_constraints"


class WorkflowStepStatus(str, Enum):
    """Status values for workflow steps."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRY = "retry"


class BatchJob(Base, TimeStampedMixin):
    """Model for batch processing jobs."""
    
    __tablename__ = "batch_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    operation_type = Column(String(50), nullable=False, index=True)
    status = Column(String(20), default=BatchJobStatus.PENDING, nullable=False, index=True)
    
    # Job configuration
    config = Column(JSON, default={})
    input_models = Column(JSON, default=[])  # List of model IDs
    output_location = Column(String(500))
    
    # Execution details
    start_time = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    end_time = Column(DateTime(timezone=True))
    duration_seconds = Column(Numeric(10, 2))
    
    # Progress tracking
    total_items = Column(Integer, default=0)
    processed_items = Column(Integer, default=0)
    failed_items = Column(Integer, default=0)
    skipped_items = Column(Integer, default=0)
    
    # Results and errors
    results = Column(JSON, default={})
    errors = Column(JSON, default=[])
    warnings = Column(JSON, default=[])
    
    # Resource usage
    cpu_seconds = Column(Numeric(10, 2))
    memory_mb_peak = Column(Numeric(10, 2))
    
    # Retry configuration
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    retry_delay_seconds = Column(Integer, default=60)
    
    # Relationships
    user = relationship("User", back_populates="batch_jobs")
    quality_checks = relationship("QualityCheck", back_populates="batch_job", cascade="all, delete-orphan")
    workflow_executions = relationship("WorkflowExecution", back_populates="batch_job", cascade="all, delete-orphan")
    
    @hybrid_property
    def progress_percentage(self) -> float:
        """Calculate job progress as percentage."""
        if self.total_items == 0:
            return 0.0
        return min(100.0, (self.processed_items / self.total_items) * 100)
    
    @hybrid_property
    def success_rate(self) -> float:
        """Calculate success rate of processed items."""
        if self.processed_items == 0:
            return 0.0
        successful = self.processed_items - self.failed_items
        return (successful / self.processed_items) * 100
    
    def __repr__(self) -> str:
        return f"<BatchJob(id={self.id}, name='{self.name}', status={self.status})>"


class QualityCheck(Base, TimeStampedMixin):
    """Model for quality check results on CAD models."""
    
    __tablename__ = "quality_checks"
    __table_args__ = (
        UniqueConstraint("batch_job_id", "model_id", "check_type", name="uq_quality_check"),
    )
    
    id = Column(Integer, primary_key=True, index=True)
    batch_job_id = Column(Integer, ForeignKey("batch_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    model_id = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=False, index=True)
    check_type = Column(String(50), nullable=False, index=True)
    
    # Check execution
    status = Column(String(20), default=BatchJobStatus.PENDING, nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    end_time = Column(DateTime(timezone=True))
    duration_seconds = Column(Numeric(10, 3))
    
    # Check results
    passed = Column(Boolean)
    score = Column(Numeric(5, 2))  # Quality score 0-100
    severity = Column(String(20))  # critical, major, minor, info
    
    # Detailed findings
    issues_found = Column(Integer, default=0)
    issues_fixed = Column(Integer, default=0)
    findings = Column(JSON, default=[])
    
    # Recommendations
    recommendations = Column(JSON, default=[])
    auto_fix_available = Column(Boolean, default=False)
    auto_fix_applied = Column(Boolean, default=False)
    
    # Metrics
    metrics = Column(JSON, default={})
    
    # Error handling
    error_message = Column(Text)
    error_details = Column(JSON)
    
    # Relationships
    batch_job = relationship("BatchJob", back_populates="quality_checks")
    model = relationship("Model")
    
    def __repr__(self) -> str:
        return f"<QualityCheck(id={self.id}, model_id={self.model_id}, check_type={self.check_type}, passed={self.passed})>"


class WorkflowExecution(Base, TimeStampedMixin):
    """Model for workflow execution tracking."""
    
    __tablename__ = "workflow_executions"
    
    id = Column(Integer, primary_key=True, index=True)
    batch_job_id = Column(Integer, ForeignKey("batch_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    workflow_name = Column(String(255), nullable=False)
    workflow_version = Column(String(50))
    
    # Execution details
    status = Column(String(20), default=WorkflowStepStatus.PENDING, nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    end_time = Column(DateTime(timezone=True))
    duration_seconds = Column(Numeric(10, 2))
    
    # Workflow configuration
    config = Column(JSON, default={})
    parameters = Column(JSON, default={})
    
    # Step tracking
    total_steps = Column(Integer, default=0)
    completed_steps = Column(Integer, default=0)
    failed_steps = Column(Integer, default=0)
    current_step = Column(String(255))
    
    # Step details
    steps = Column(JSON, default=[])
    step_results = Column(JSON, default={})
    
    # Error handling
    error_message = Column(Text)
    error_step = Column(String(255))
    error_details = Column(JSON)
    
    # Retry information
    retry_count = Column(Integer, default=0)
    can_retry = Column(Boolean, default=True)
    
    # Relationships
    batch_job = relationship("BatchJob", back_populates="workflow_executions")
    
    @hybrid_property
    def progress_percentage(self) -> float:
        """Calculate workflow progress as percentage."""
        if self.total_steps == 0:
            return 0.0
        return min(100.0, (self.completed_steps / self.total_steps) * 100)
    
    def __repr__(self) -> str:
        return f"<WorkflowExecution(id={self.id}, workflow_name='{self.workflow_name}', status={self.status})>"


def calculate_duration(mapper, connection, target):
    """Generic function to calculate duration for timed operations."""
    if target.end_time and target.start_time:
        duration = (target.end_time - target.start_time).total_seconds()
        target.duration_seconds = Decimal(str(duration))


# Register event listeners for duration calculation
event.listen(BatchJob, "before_update", calculate_duration)
event.listen(QualityCheck, "before_update", calculate_duration)
event.listen(WorkflowExecution, "before_update", calculate_duration)