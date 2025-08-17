"""Simulation run model for collision detection and verification.

Enterprise-grade simulation execution tracking with strict Task Master ERD compliance.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, ForeignKey, Index,
    DateTime, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import JobStatus


class SimRun(Base, TimestampMixin):
    """Simulation runs for collision detection and verification.
    
    Task Master ERD Compliance:
    - job_id FK with RESTRICT cascade behavior
    - params JSONB for simulation configuration
    - metrics JSONB for performance data
    - status enum with proper indexing
    - Enterprise security and audit trail
    """
    
    __tablename__ = "sim_runs"
    
    # Primary key
    id: Mapped[int] = mapped_column(
        primary_key=True, 
        autoincrement=True
    )
    
    # Foreign key with RESTRICT behavior per ERD
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT", name="fk_sim_runs_job_id"),
        nullable=False,
        index=True
    )
    
    # Simulation configuration parameters (Task Master ERD requirement)
    params: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict
    )
    
    # Performance and execution metrics (Task Master ERD requirement) 
    metrics: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict
    )
    
    # Status with enterprise indexing
    status: Mapped[JobStatus] = mapped_column(
        SQLEnum(JobStatus, name="sim_run_status"),
        nullable=False,
        default=JobStatus.PENDING,
        index=True
    )
    
    # Relationships
    job: Mapped["Job"] = relationship(
        "Job", 
        back_populates="sim_runs",
        foreign_keys=[job_id]
    )
    
    # Enterprise-grade indexing strategy
    __table_args__ = (
        Index(
            'idx_sim_runs_job_id_status', 
            'job_id', 
            'status'
        ),
        Index(
            'idx_sim_runs_status', 
            'status',
            postgresql_where="status IN ('pending', 'running')"
        ),
        Index(
            'idx_sim_runs_created_at', 
            'created_at'
        )
    )
    
    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"<SimRun(id={self.id}, job_id={self.job_id}, "
            f"status={self.status.value})>"
        )
    
    def __str__(self) -> str:
        """User-friendly representation."""
        return f"Simulation Run #{self.id} - {self.status.value}"
    
    @property
    def is_active(self) -> bool:
        """Check if simulation run is currently active."""
        return self.status in [JobStatus.PENDING, JobStatus.RUNNING]
    
    @property
    def is_completed(self) -> bool:
        """Check if simulation run completed successfully."""
        return self.status == JobStatus.COMPLETED
    
    @property
    def is_failed(self) -> bool:
        """Check if simulation run failed."""
        return self.status == JobStatus.FAILED
    
    def get_param(self, key: str, default=None):
        """Get simulation parameter value safely."""
        return self.params.get(key, default)
    
    def set_param(self, key: str, value) -> None:
        """Set simulation parameter value safely."""
        if self.params is None:
            self.params = {}
        self.params[key] = value
    
    def get_metric(self, key: str, default=None):
        """Get metric value safely."""
        return self.metrics.get(key, default)
    
    def set_metric(self, key: str, value) -> None:
        """Set metric value safely."""
        if self.metrics is None:
            self.metrics = {}
        self.metrics[key] = value
    
    def add_collision_results(
        self, 
        collision_count: int,
        collision_details: dict,
        severity_level: str
    ) -> None:
        """Add collision detection results."""
        self.set_metric('collision_count', collision_count)
        self.set_metric('collision_details', collision_details)
        self.set_metric('severity_level', severity_level)
        self.set_metric('updated_at', datetime.utcnow().isoformat())
    
    def add_performance_metrics(
        self, 
        simulation_time_ms: int,
        accuracy_percentage: float,
        memory_usage_mb: float
    ) -> None:
        """Add simulation performance metrics."""
        self.set_metric('simulation_time_ms', simulation_time_ms)
        self.set_metric('accuracy_percentage', accuracy_percentage)
        self.set_metric('memory_usage_mb', memory_usage_mb)
        self.set_metric('updated_at', datetime.utcnow().isoformat())