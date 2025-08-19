"""
Job model for asynchronous task processing.
"""

from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import JobStatus, JobType


class Job(Base, TimestampMixin):
    """Asynchronous job queue and processing."""

    __tablename__ = "jobs"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Idempotency
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        unique=True,
        index=True
    )

    # Foreign keys
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        index=True
    )

    # Job type and status
    type: Mapped[JobType] = mapped_column(
        SQLEnum(JobType),
        nullable=False,
        index=True
    )
    status: Mapped[JobStatus] = mapped_column(
        SQLEnum(JobStatus),
        nullable=False,
        default=JobStatus.PENDING,
        index=True
    )

    # Priority and scheduling
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )

    # Task execution
    task_id: Mapped[str | None] = mapped_column(
        String(255),
        index=True
    )

    # Input/Output (Task 2.3 requirements)
    params: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default={},
        name="input_params"  # Database column remains input_params
    )
    output_data: Mapped[dict | None] = mapped_column(JSONB)

    # Progress tracking
    progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )

    # Execution timestamps
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        index=True
    )

    # Error handling
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(String(1000))

    # Retry configuration
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )
    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3
    )

    # Timeout
    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3600  # 1 hour default
    )

    # Performance metrics
    metrics: Mapped[dict | None] = mapped_column(JSONB)

    # Relationships
    user: Mapped[Optional["User"]] = relationship("User", back_populates="jobs")
    artefacts: Mapped[list["Artefact"]] = relationship(
        "Artefact",
        back_populates="job",
        cascade="all, delete-orphan"
    )
    cam_runs: Mapped[list["CamRun"]] = relationship(
        "CamRun",
        back_populates="job"
    )
    sim_runs: Mapped[list["SimRun"]] = relationship(
        "SimRun",
        back_populates="job"
    )

    # Constraints and indexes (Task 2.3 requirements)
    __table_args__ = (
        CheckConstraint('progress >= 0 AND progress <= 100',
                       name='ck_jobs_progress_valid'),
        CheckConstraint('retry_count >= 0', name='ck_jobs_retry_count_non_negative'),
        CheckConstraint('max_retries >= 0', name='ck_jobs_max_retries_non_negative'),
        CheckConstraint('timeout_seconds > 0', name='ck_jobs_timeout_positive'),
        Index('idx_jobs_status_created_at', 'status', 'created_at'),
        Index('idx_jobs_user_id', 'user_id'),
        Index('idx_jobs_type', 'type'),
        Index('idx_jobs_idempotency_key', 'idempotency_key',
              postgresql_where='idempotency_key IS NOT NULL'),
        Index('idx_jobs_metrics', 'metrics',
              postgresql_using='gin',
              postgresql_where='metrics IS NOT NULL'),
        Index('idx_jobs_input_params', 'input_params',
              postgresql_using='gin',
              postgresql_where='input_params IS NOT NULL'),
    )

    def __repr__(self) -> str:
        return f"<Job(id={self.id}, type={self.type.value}, status={self.status.value})>"

    @property
    def is_complete(self) -> bool:
        """Check if job is in a terminal state."""
        return self.status in [
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMEOUT
        ]

    @property
    def is_running(self) -> bool:
        """Check if job is currently running."""
        return self.status == JobStatus.RUNNING

    @property
    def can_retry(self) -> bool:
        """Check if job can be retried."""
        return (
            self.status == JobStatus.FAILED and
            self.retry_count < self.max_retries
        )

    @property
    def execution_time(self) -> timedelta | None:
        """Calculate job execution time."""
        if not self.started_at:
            return None
        end_time = self.finished_at or datetime.now(UTC)
        return end_time - self.started_at

    @property
    def is_timeout(self) -> bool:
        """Check if job has timed out."""
        if not self.started_at or self.is_complete:
            return False
        elapsed = (datetime.now(UTC) - self.started_at).total_seconds()
        return elapsed > self.timeout_seconds

    def set_running(self, task_id: str):
        """Mark job as running."""
        self.status = JobStatus.RUNNING
        self.task_id = task_id
        self.started_at = datetime.now(UTC)
        self.progress = 0

    def set_completed(self, output_data: dict = None):
        """Mark job as completed."""
        self.status = JobStatus.COMPLETED
        self.finished_at = datetime.now(UTC)
        self.progress = 100
        if output_data:
            self.output_data = output_data

    def set_failed(self, error_code: str, error_message: str):
        """Mark job as failed."""
        self.status = JobStatus.FAILED
        self.finished_at = datetime.now(UTC)
        self.error_code = error_code
        self.error_message = error_message
        self.retry_count += 1

    def set_cancelled(self):
        """Mark job as cancelled."""
        self.status = JobStatus.CANCELLED
        self.finished_at = datetime.now(UTC)

    def update_progress(self, progress: int, message: str = None):
        """Update job progress."""
        self.progress = max(0, min(100, progress))
        if message and not self.metrics:
            self.metrics = {}
        if message:
            self.metrics['last_progress_message'] = message
            self.metrics['last_progress_update'] = datetime.now(UTC).isoformat()
