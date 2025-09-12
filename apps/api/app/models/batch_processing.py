"""
Database models for Batch Processing and Automation Framework (Task 7.23)

Provides SQLAlchemy models for:
- Batch jobs and execution history
- Workflow definitions and executions
- Scheduled jobs and triggers
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    event
)
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property

from .base import Base, TimestampMixin
from .enums import (
    BatchStatus, 
    BatchItemStatus, 
    ProcessingStrategy,
    WorkflowStatus, 
    StepStatus, 
    StepType, 
    ErrorHandling,
    JobTriggerType, 
    ScheduledJobStatus
)


class BatchJob(Base, TimestampMixin):
    """Batch processing job definition and history."""
    
    __tablename__ = "batch_jobs"
    __table_args__ = (
        Index("ix_batch_jobs_status_created", "status", "created_at"),
        Index("ix_batch_jobs_user_status", "user_id", "status"),
        {"comment": "Batch processing jobs and execution history"}
    )
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String(64), unique=True, nullable=False, index=True, comment="Unique batch identifier")
    
    # Job metadata
    name = Column(String(255), nullable=False, comment="Job name")
    description = Column(Text, comment="Job description")
    operation = Column(String(100), nullable=False, index=True, comment="Operation type")
    
    # Status and progress
    status = Column(
        Enum(BatchStatus, native_enum=False),
        nullable=False,
        default=BatchStatus.CREATED,
        index=True,
        comment="Current status"
    )
    total_items = Column(Integer, nullable=False, default=0, comment="Total items to process")
    processed_items = Column(Integer, nullable=False, default=0, comment="Items processed")
    successful_items = Column(Integer, nullable=False, default=0, comment="Successfully processed items")
    failed_items = Column(Integer, nullable=False, default=0, comment="Failed items")
    skipped_items = Column(Integer, nullable=False, default=0, comment="Skipped items")
    
    # Processing configuration
    strategy = Column(
        Enum(ProcessingStrategy, native_enum=False),
        nullable=False,
        default=ProcessingStrategy.ADAPTIVE,
        comment="Processing strategy"
    )
    max_workers = Column(Integer, comment="Maximum parallel workers")
    chunk_size = Column(Integer, default=10, comment="Items per chunk")
    max_retries = Column(Integer, default=3, comment="Maximum retry attempts")
    continue_on_error = Column(Boolean, default=True, comment="Continue processing on errors")
    
    # Timing
    start_time = Column(DateTime(timezone=True), comment="Execution start time")
    end_time = Column(DateTime(timezone=True), comment="Execution end time")
    duration_ms = Column(Float, comment="Total duration in milliseconds")
    
    # Results and errors
    results = Column(JSON, default=list, comment="Processing results")
    errors = Column(JSON, default=dict, comment="Error details")
    statistics = Column(JSON, default=dict, comment="Processing statistics")
    
    # User and metadata
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), index=True)
    metadata_ = Column("metadata", JSON, default=dict, comment="Additional metadata")
    
    # Relationships
    user = relationship("User")
    items = relationship("BatchJobItem", back_populates="batch_job", cascade="all, delete-orphan")
    
    @validates("batch_id")
    def validate_batch_id(self, key: str, value: str) -> str:
        """Validate batch ID format."""
        if not value or len(value) > 64:
            # Use error code instead of hardcoded message for localization
            raise ValueError("INVALID_BATCH_ID")
        return value
    
    @hybrid_property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.total_items == 0:
            return 0.0
        return (self.processed_items / self.total_items) * 100
    
    @hybrid_property
    def is_complete(self) -> bool:
        """Check if job is complete."""
        return self.status in [BatchStatus.COMPLETED, BatchStatus.FAILED, BatchStatus.CANCELLED]
    
    @hybrid_property
    def success_rate(self) -> float:
        """Calculate success rate."""
        if self.processed_items == 0:
            return 0.0
        return (self.successful_items / self.processed_items) * 100
    
    def __repr__(self) -> str:
        return f"<BatchJob(id={self.id}, batch_id={self.batch_id}, status={self.status})>"


class BatchJobItem(Base, TimestampMixin):
    """Individual item in a batch job."""
    
    __tablename__ = "batch_job_items"
    __table_args__ = (
        Index("ix_batch_job_items_batch_status", "batch_job_id", "status"),
        {"comment": "Individual items in batch processing jobs"}
    )
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    
    # Foreign keys
    batch_job_id = Column(Integer, ForeignKey("batch_jobs.id", ondelete="CASCADE"), nullable=False)
    
    # Item metadata
    item_id = Column(String(64), nullable=False, comment="Item identifier")
    priority = Column(Integer, default=0, comment="Processing priority (0-10)")
    
    # Status and processing
    status = Column(
        Enum(BatchItemStatus, native_enum=False),
        nullable=False,
        default=BatchItemStatus.PENDING,
        index=True,
        comment="Item status"
    )
    retries = Column(Integer, default=0, comment="Retry attempts")
    processing_time_ms = Column(Float, comment="Processing duration in milliseconds")
    
    # Data and results
    input_data = Column(JSON, comment="Input data for processing")
    output_data = Column(JSON, comment="Processing output")
    error = Column(Text, comment="Error message if failed")
    metadata_ = Column("metadata", JSON, default=dict, comment="Additional metadata")
    
    # Relationships
    batch_job = relationship("BatchJob", back_populates="items")
    
    def __repr__(self) -> str:
        return f"<BatchJobItem(id={self.id}, item_id={self.item_id}, status={self.status})>"


class WorkflowDefinition(Base, TimestampMixin):
    """Workflow definition and configuration."""
    
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_workflow_name_version"),
        Index("ix_workflow_definitions_active", "is_active"),
        {"comment": "Workflow definitions and configurations"}
    )
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(String(64), unique=True, nullable=False, index=True, comment="Unique workflow identifier")
    
    # Workflow metadata
    name = Column(String(255), nullable=False, index=True, comment="Workflow name")
    description = Column(Text, comment="Workflow description")
    version = Column(String(20), nullable=False, default="1.0.0", comment="Version number")
    is_active = Column(Boolean, default=True, index=True, comment="Is workflow active")
    
    # Workflow structure
    steps = Column(JSON, nullable=False, comment="Workflow steps definition")
    entry_point = Column(String(64), comment="Entry point step ID")
    global_timeout = Column(Integer, comment="Global timeout in seconds")
    
    # Success/failure handlers
    on_success = Column(JSON, comment="Steps to execute on success")
    on_failure = Column(JSON, comment="Steps to execute on failure")
    
    # User and metadata
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    metadata_ = Column("metadata", JSON, default=dict, comment="Additional metadata")
    
    # Turkish messages
    messages = Column(JSON, default=dict, comment="Localized messages")
    
    # Relationships
    executions = relationship("WorkflowExecution", back_populates="definition", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])
    
    @validates("version")
    def validate_version(self, key: str, value: str) -> str:
        """Validate version format."""
        if not re.match(r"^\d+\.\d+\.\d+$", value):
            raise ValueError("Geçersiz versiyon formatı (örn: 1.0.0)")
        return value
    
    def __repr__(self) -> str:
        return f"<WorkflowDefinition(id={self.id}, name={self.name}, version={self.version})>"


class WorkflowExecution(Base, TimestampMixin):
    """Workflow execution instance."""
    
    __tablename__ = "workflow_executions"
    __table_args__ = (
        Index("ix_workflow_executions_status_started", "status", "start_time"),
        Index("ix_workflow_executions_definition_status", "workflow_definition_id", "status"),
        {"comment": "Workflow execution instances and history"}
    )
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(String(64), unique=True, nullable=False, index=True, comment="Unique execution identifier")
    
    # Foreign keys
    workflow_definition_id = Column(Integer, ForeignKey("workflow_definitions.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    
    # Execution status
    status = Column(
        Enum(WorkflowStatus, native_enum=False),
        nullable=False,
        default=WorkflowStatus.CREATED,
        index=True,
        comment="Execution status"
    )
    current_step = Column(String(64), comment="Currently executing step ID")
    
    # Data and context
    input_data = Column(JSON, default=dict, comment="Input data for execution")
    context = Column(JSON, default=dict, comment="Execution context")
    step_results = Column(JSON, default=dict, comment="Results from each step")
    
    # Timing
    start_time = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), comment="Execution start time")
    end_time = Column(DateTime(timezone=True), comment="Execution end time")
    duration_ms = Column(Float, comment="Total duration in milliseconds")
    
    # Error handling
    error = Column(Text, comment="Error message if failed")
    metadata_ = Column("metadata", JSON, default=dict, comment="Additional metadata")
    
    # Relationships
    definition = relationship("WorkflowDefinition", back_populates="executions")
    user = relationship("User", foreign_keys=[user_id])
    
    @hybrid_property
    def is_running(self) -> bool:
        """Check if execution is running."""
        return self.status == WorkflowStatus.RUNNING
    
    @hybrid_property
    def is_complete(self) -> bool:
        """Check if execution is complete."""
        return self.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED]
    
    def __repr__(self) -> str:
        return f"<WorkflowExecution(id={self.id}, execution_id={self.execution_id}, status={self.status})>"


class ScheduledJob(Base, TimestampMixin):
    """Scheduled job configuration."""
    
    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_scheduled_job_id"),
        Index("ix_scheduled_jobs_enabled_next_run", "enabled", "next_run_time"),
        {"comment": "Scheduled job configurations"}
    )
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(64), unique=True, nullable=False, index=True, comment="Unique job identifier")
    
    # Job metadata
    name = Column(String(255), nullable=False, comment="Job name")
    description = Column(Text, comment="Job description")
    function = Column(String(255), nullable=False, comment="Function to execute")
    
    # Trigger configuration
    trigger_type = Column(
        Enum(JobTriggerType, native_enum=False),
        nullable=False,
        comment="Trigger type"
    )
    trigger_args = Column(JSON, nullable=False, comment="Trigger configuration")
    
    # Execution configuration
    args = Column(JSON, default=list, comment="Function arguments")
    kwargs = Column(JSON, default=dict, comment="Function keyword arguments")
    max_instances = Column(Integer, default=1, comment="Maximum concurrent instances")
    misfire_grace_time = Column(Integer, default=60, comment="Misfire grace time in seconds")
    coalesce = Column(Boolean, default=True, comment="Coalesce missed executions")
    
    # Status
    enabled = Column(Boolean, default=True, index=True, comment="Is job enabled")
    next_run_time = Column(DateTime(timezone=True), index=True, comment="Next scheduled run time")
    last_run_time = Column(DateTime(timezone=True), comment="Last execution time")
    
    # User and metadata
    created_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    metadata_ = Column("metadata", JSON, default=dict, comment="Additional metadata")
    
    # Relationships
    executions = relationship("ScheduledJobExecution", back_populates="scheduled_job", cascade="all, delete-orphan")
    creator = relationship("User", foreign_keys=[created_by])
    
    def __repr__(self) -> str:
        return f"<ScheduledJob(id={self.id}, job_id={self.job_id}, name={self.name})>"


class ScheduledJobExecution(Base, TimestampMixin):
    """Scheduled job execution history."""
    
    __tablename__ = "scheduled_job_executions"
    __table_args__ = (
        Index("ix_scheduled_job_executions_job_started", "scheduled_job_id", "start_time"),
        Index("ix_scheduled_job_executions_status", "status"),
        {"comment": "Scheduled job execution history"}
    )
    
    # Primary key
    id = Column(Integer, primary_key=True, index=True)
    execution_id = Column(String(64), unique=True, nullable=False, index=True, comment="Unique execution identifier")
    
    # Foreign keys
    scheduled_job_id = Column(Integer, ForeignKey("scheduled_jobs.id", ondelete="CASCADE"), nullable=False)
    
    # Execution details
    status = Column(
        Enum(ScheduledJobStatus, native_enum=False),
        nullable=False,
        index=True,
        comment="Execution status"
    )
    scheduled_time = Column(DateTime(timezone=True), nullable=False, comment="Scheduled execution time")
    start_time = Column(DateTime(timezone=True), comment="Actual start time")
    end_time = Column(DateTime(timezone=True), comment="Actual end time")
    duration_ms = Column(Float, comment="Execution duration in milliseconds")
    
    # Results
    result = Column(JSON, comment="Execution result")
    error = Column(Text, comment="Error message if failed")
    metadata_ = Column("metadata", JSON, default=dict, comment="Additional metadata")
    
    # Relationships
    scheduled_job = relationship("ScheduledJob", back_populates="executions")
    
    @hybrid_property
    def was_missed(self) -> bool:
        """Check if execution was missed."""
        return self.status == ScheduledJobStatus.MISSED
    
    def __repr__(self) -> str:
        return f"<ScheduledJobExecution(id={self.id}, execution_id={self.execution_id}, status={self.status})>"


# Event listeners for validation and auto-updates
def update_duration_metrics(target):
    """Update duration metrics for any model with start/end times."""
    if target.start_time and target.end_time:
        delta = target.end_time - target.start_time
        target.duration_ms = delta.total_seconds() * 1000


@event.listens_for(BatchJob, "before_insert")
@event.listens_for(BatchJob, "before_update")
def update_batch_job_metrics(mapper, connection, target):
    """Update batch job metrics before save."""
    update_duration_metrics(target)


@event.listens_for(WorkflowExecution, "before_update")
def update_workflow_execution_metrics(mapper, connection, target):
    """Update workflow execution metrics before save."""
    update_duration_metrics(target)


@event.listens_for(ScheduledJobExecution, "before_update")
def update_scheduled_job_execution_metrics(mapper, connection, target):
    """Update scheduled job execution metrics before save."""
    update_duration_metrics(target)