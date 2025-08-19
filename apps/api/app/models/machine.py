"""
Machine model for CNC machine configurations.
"""

from decimal import Decimal
from typing import Optional, List

from sqlalchemy import String, Integer, Boolean, Index, Numeric, CheckConstraint, Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import MachineType


class Machine(Base, TimestampMixin):
    """CNC machine configurations."""

    __tablename__ = "machines"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Machine identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    manufacturer: Mapped[Optional[str]] = mapped_column(String(100))
    model: Mapped[Optional[str]] = mapped_column(String(100))

    # Machine type
    type: Mapped[MachineType] = mapped_column(SQLEnum(MachineType), nullable=False, index=True)

    # Machine capabilities
    axes: Mapped[int] = mapped_column(Integer, nullable=False)

    # Work envelope (in mm)
    work_envelope_x_mm: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    work_envelope_y_mm: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    work_envelope_z_mm: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Spindle specifications
    spindle_max_rpm: Mapped[int] = mapped_column(Integer, nullable=False)
    spindle_power_kw: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))

    # Tool changer
    tool_capacity: Mapped[Optional[int]] = mapped_column(Integer)

    # Controller
    controller: Mapped[Optional[str]] = mapped_column(String(100))
    post_processor: Mapped[str] = mapped_column(String(100), nullable=False)

    # Operating cost
    hourly_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))

    # Additional specifications
    specifications: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relationships
    cam_runs: Mapped[List["CamRun"]] = relationship("CamRun", back_populates="machine")

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint("axes >= 3 AND axes <= 9", name="ck_machines_axes_valid"),
        CheckConstraint("work_envelope_x_mm > 0", name="ck_machines_envelope_x_positive"),
        CheckConstraint("work_envelope_y_mm > 0", name="ck_machines_envelope_y_positive"),
        CheckConstraint("work_envelope_z_mm > 0", name="ck_machines_envelope_z_positive"),
        CheckConstraint("spindle_max_rpm > 0", name="ck_machines_spindle_rpm_positive"),
        CheckConstraint("spindle_power_kw > 0", name="ck_machines_spindle_power_positive"),
        CheckConstraint("tool_capacity > 0", name="ck_machines_tool_capacity_positive"),
        CheckConstraint("hourly_rate >= 0", name="ck_machines_hourly_rate_non_negative"),
        Index("idx_machines_active", "is_active", "name", postgresql_where="is_active = true"),
    )

    def __repr__(self) -> str:
        return f"<Machine(id={self.id}, name={self.name}, type={self.type.value})>"

    @property
    def work_volume_cubic_mm(self) -> Decimal:
        """Calculate work volume in cubic millimeters."""
        return self.work_envelope_x_mm * self.work_envelope_y_mm * self.work_envelope_z_mm

    @property
    def work_volume_cubic_cm(self) -> Decimal:
        """Calculate work volume in cubic centimeters."""
        return self.work_volume_cubic_mm / 1000

    @property
    def max_feed_rate(self) -> Optional[float]:
        """Get maximum feed rate from specifications."""
        if not self.specifications:
            return None
        return self.specifications.get("max_feed_rate")

    @property
    def rapid_feed_rate(self) -> Optional[float]:
        """Get rapid feed rate from specifications."""
        if not self.specifications:
            return None
        return self.specifications.get("rapid_feed_rate")

    def can_machine_part(self, x: float, y: float, z: float) -> bool:
        """Check if part dimensions fit within work envelope."""
        return (
            x <= float(self.work_envelope_x_mm)
            and y <= float(self.work_envelope_y_mm)
            and z <= float(self.work_envelope_z_mm)
        )
