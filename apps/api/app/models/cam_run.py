"""
CAM run model for toolpath generation and processing.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String, Integer, ForeignKey, Index,
    DateTime, Numeric, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import CamStrategy, JobStatus


class CamRun(Base, TimestampMixin):
    """CAM (Computer-Aided Manufacturing) processing runs."""
    
    __tablename__ = "cam_runs"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Foreign keys
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    model_id: Mapped[int] = mapped_column(
        ForeignKey("models.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    
    # CAM configuration
    strategy: Mapped[CamStrategy] = mapped_column(
        SQLEnum(CamStrategy),
        nullable=False
    )
    
    # Tool paths
    tool_paths: Mapped[Optional[dict]] = mapped_column(JSONB)
    
    # Cutting parameters
    cutting_params: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default={}
    )
    
    # Performance estimates
    estimated_time_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    material_removal_cc: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2)
    )
    
    # Output
    output_s3_key: Mapped[Optional[str]] = mapped_column(String(1024))
    
    # Status
    status: Mapped[JobStatus] = mapped_column(
        SQLEnum(JobStatus),
        nullable=False,
        default=JobStatus.PENDING,
        index=True
    )
    
    # Error information
    error_details: Mapped[Optional[str]] = mapped_column(String(1000))
    
    # Completion timestamp
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    
    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="cam_runs")
    model: Mapped["Model"] = relationship("Model", back_populates="cam_runs")
    sim_runs: Mapped[list["SimRun"]] = relationship(
        "SimRun",
        back_populates="cam_run",
        cascade="all, delete-orphan"
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_cam_runs_status', 'status',
              postgresql_where="status != 'completed'"),
    )
    
    def __repr__(self) -> str:
        return f"<CamRun(id={self.id}, strategy={self.strategy.value}, status={self.status.value})>"
    
    @property
    def is_complete(self) -> bool:
        """Check if CAM run is complete."""
        return self.status == JobStatus.COMPLETED
    
    @property
    def estimated_time_minutes(self) -> Optional[float]:
        """Get estimated time in minutes."""
        if not self.estimated_time_seconds:
            return None
        return self.estimated_time_seconds / 60.0
    
    @property
    def estimated_time_hours(self) -> Optional[float]:
        """Get estimated time in hours."""
        if not self.estimated_time_seconds:
            return None
        return self.estimated_time_seconds / 3600.0
    
    def get_cutting_param(self, param: str, default=None):
        """Get specific cutting parameter."""
        return self.cutting_params.get(param, default)
    
    def set_cutting_param(self, param: str, value):
        """Set specific cutting parameter."""
        if not self.cutting_params:
            self.cutting_params = {}
        self.cutting_params[param] = value