"""
Simulation run model for collision detection and verification.
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
from .enums import SimulationType, SimulationStatus


class SimRun(Base, TimestampMixin):
    """Simulation runs for collision detection and verification."""
    
    __tablename__ = "sim_runs"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Foreign keys
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    cam_run_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cam_runs.id", ondelete="CASCADE"),
        index=True
    )
    machine_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("machines.id", ondelete="RESTRICT"),
        index=True
    )
    
    # Simulation configuration
    type: Mapped[SimulationType] = mapped_column(
        SQLEnum(SimulationType),
        nullable=False
    )
    
    # Collision detection
    collision_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )
    collision_details: Mapped[Optional[dict]] = mapped_column(JSONB)
    
    # Material removal accuracy
    material_removal_accuracy: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2)
    )
    
    # Performance
    simulation_time_ms: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Output files
    video_s3_key: Mapped[Optional[str]] = mapped_column(String(1024))
    report_s3_key: Mapped[Optional[str]] = mapped_column(String(1024))
    
    # Status
    status: Mapped[SimulationStatus] = mapped_column(
        SQLEnum(SimulationStatus),
        nullable=False,
        index=True
    )
    
    # Completion timestamp
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    
    # Relationships
    job: Mapped["Job"] = relationship("Job", back_populates="sim_runs")
    cam_run: Mapped[Optional["CamRun"]] = relationship(
        "CamRun",
        back_populates="sim_runs"
    )
    machine: Mapped[Optional["Machine"]] = relationship(
        "Machine",
        back_populates="sim_runs"
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_sim_runs_cam_run_id', 'cam_run_id',
              postgresql_where='cam_run_id IS NOT NULL'),
        Index('idx_sim_runs_machine_id', 'machine_id',
              postgresql_where='machine_id IS NOT NULL'),
    )
    
    def __repr__(self) -> str:
        return f"<SimRun(id={self.id}, type={self.type.value}, status={self.status.value})>"
    
    @property
    def has_collisions(self) -> bool:
        """Check if simulation detected collisions."""
        return self.collision_count > 0
    
    @property
    def is_passed(self) -> bool:
        """Check if simulation passed."""
        return self.status in [
            SimulationStatus.PASSED,
            SimulationStatus.PASSED_WARNINGS
        ]
    
    @property
    def simulation_time_seconds(self) -> Optional[float]:
        """Get simulation time in seconds."""
        if not self.simulation_time_ms:
            return None
        return self.simulation_time_ms / 1000.0
    
    def add_collision(
        self,
        timestamp: float,
        tool_id: int,
        component: str,
        severity: str,
        position: dict
    ):
        """Add a collision to the simulation results."""
        if not self.collision_details:
            self.collision_details = {'collisions': []}
        
        self.collision_details['collisions'].append({
            'timestamp': timestamp,
            'tool_id': tool_id,
            'component': component,
            'severity': severity,
            'position': position
        })
        
        self.collision_count = len(self.collision_details['collisions'])