"""CAM run model for toolpath generation and processing.

Enterprise-grade CAM execution tracking with strict Task Master ERD compliance.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Integer, ForeignKey, Index, DateTime, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import JobStatus


class CamRun(Base, TimestampMixin):
    """CAM (Computer-Aided Manufacturing) execution runs.

    Task Master ERD Compliance:
    - job_id FK with RESTRICT cascade behavior
    - machine_id FK with RESTRICT cascade behavior
    - params JSONB for CAM configuration
    - metrics JSONB for performance data
    - status enum with proper indexing
    - Enterprise security and audit trail
    """

    __tablename__ = "cam_runs"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Foreign keys with RESTRICT behavior per ERD
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT", name="fk_cam_runs_job_id"),
        nullable=False,
        index=True,
    )

    machine_id: Mapped[int] = mapped_column(
        ForeignKey("machines.id", ondelete="RESTRICT", name="fk_cam_runs_machine_id"),
        nullable=False,
        index=True,
    )

    # CAM configuration parameters (Task Master ERD requirement)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=lambda: {})

    # Performance and execution metrics (Task Master ERD requirement)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=lambda: {})

    # Status with enterprise indexing
    status: Mapped[JobStatus] = mapped_column(
        SQLEnum(JobStatus, name="cam_run_status"),
        nullable=False,
        default=JobStatus.PENDING,
        index=True,
    )

    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="cam_runs", foreign_keys=[job_id])

    machine: Mapped["Machine"] = relationship(
        "Machine", back_populates="cam_runs", foreign_keys=[machine_id]
    )

    # Enterprise-grade indexing strategy
    __table_args__ = (
        Index("idx_cam_runs_job_id_status", "job_id", "status"),
        Index(
            "idx_cam_runs_machine_status",
            "machine_id",
            "status",
            postgresql_where="status IN ('pending', 'running')",
        ),
        Index("idx_cam_runs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return (
            f"<CamRun(id={self.id}, job_id={self.job_id}, "
            f"machine_id={self.machine_id}, status={self.status.value})>"
        )

    def __str__(self) -> str:
        """User-friendly representation."""
        return f"CAM Run #{self.id} - {self.status.value}"

    @property
    def is_active(self) -> bool:
        """Check if CAM run is currently active."""
        return self.status in [JobStatus.PENDING, JobStatus.RUNNING]

    @property
    def is_completed(self) -> bool:
        """Check if CAM run completed successfully."""
        return self.status == JobStatus.COMPLETED

    @property
    def is_failed(self) -> bool:
        """Check if CAM run failed."""
        return self.status == JobStatus.FAILED

    def get_param(self, key: str, default=None):
        """Get CAM parameter value safely."""
        return self.params.get(key, default)

    def set_param(self, key: str, value) -> None:
        """Set CAM parameter value safely."""
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

    def add_execution_metrics(
        self, execution_time_ms: int, toolpath_length_mm: float, material_removed_cm3: float
    ) -> None:
        """Add execution performance metrics."""
        self.set_metric("execution_time_ms", execution_time_ms)
        self.set_metric("toolpath_length_mm", toolpath_length_mm)
        self.set_metric("material_removed_cm3", material_removed_cm3)
        self.set_metric("updated_at", datetime.now(timezone.utc).isoformat())
