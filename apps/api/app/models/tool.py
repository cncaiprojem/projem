"""
Tool model for cutting tool inventory.
"""

from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Index, Integer, Numeric, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin
from .enums import ToolMaterial, ToolType


class Tool(Base, TimestampMixin):
    """Cutting tool inventory."""

    __tablename__ = "tools"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Tool identification
    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False
    )
    type: Mapped[ToolType] = mapped_column(
        SQLEnum(ToolType),
        nullable=False,
        index=True
    )
    material: Mapped[ToolMaterial | None] = mapped_column(
        SQLEnum(ToolMaterial),
        index=True
    )
    coating: Mapped[str | None] = mapped_column(String(100))

    # Manufacturer information
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    part_number: Mapped[str | None] = mapped_column(
        String(100),
        index=True
    )

    # Tool geometry
    diameter_mm: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3),
        index=True
    )
    flute_count: Mapped[int | None] = mapped_column(Integer)
    flute_length_mm: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2)
    )
    overall_length_mm: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2)
    )
    shank_diameter_mm: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2)
    )
    corner_radius_mm: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 3)
    )
    helix_angle_deg: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2)
    )

    # Cutting parameters
    max_depth_of_cut_mm: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2)
    )

    # Additional specifications
    specifications: Mapped[dict | None] = mapped_column(JSONB)

    # Tool life and cost
    tool_life_minutes: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 2)
    )

    # Inventory management
    quantity_available: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )
    minimum_stock: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0
    )
    location: Mapped[str | None] = mapped_column(String(100))

    # Status
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True
    )

    # Constraints and indexes
    __table_args__ = (
        CheckConstraint('diameter_mm > 0',
                       name='ck_tools_diameter_positive'),
        CheckConstraint('flute_count > 0',
                       name='ck_tools_flute_count_positive'),
        CheckConstraint('flute_length_mm > 0',
                       name='ck_tools_flute_length_positive'),
        CheckConstraint('overall_length_mm > 0',
                       name='ck_tools_overall_length_positive'),
        CheckConstraint('shank_diameter_mm > 0',
                       name='ck_tools_shank_diameter_positive'),
        CheckConstraint('corner_radius_mm >= 0',
                       name='ck_tools_corner_radius_non_negative'),
        CheckConstraint('helix_angle_deg >= 0 AND helix_angle_deg <= 90',
                       name='ck_tools_helix_angle_valid'),
        CheckConstraint('max_depth_of_cut_mm > 0',
                       name='ck_tools_max_doc_positive'),
        CheckConstraint('tool_life_minutes > 0',
                       name='ck_tools_life_positive'),
        CheckConstraint('cost >= 0',
                       name='ck_tools_cost_non_negative'),
        CheckConstraint('quantity_available >= 0',
                       name='ck_tools_quantity_non_negative'),
        CheckConstraint('minimum_stock >= 0',
                       name='ck_tools_min_stock_non_negative'),
        Index('idx_tools_material', 'material',
              postgresql_where='material IS NOT NULL'),
        Index('idx_tools_part_number', 'part_number',
              postgresql_where='part_number IS NOT NULL'),
        Index('idx_tools_diameter', 'diameter_mm',
              postgresql_where='diameter_mm IS NOT NULL'),
        Index('idx_tools_inventory', 'quantity_available',
              postgresql_where='quantity_available < minimum_stock'),
    )

    def __repr__(self) -> str:
        return f"<Tool(id={self.id}, name={self.name}, type={self.type.value})>"

    @property
    def is_endmill(self) -> bool:
        """Check if tool is an endmill."""
        endmill_types = [
            ToolType.ENDMILL_FLAT,
            ToolType.ENDMILL_BALL,
            ToolType.ENDMILL_BULL,
            ToolType.ENDMILL_CHAMFER,
            ToolType.ENDMILL_TAPER
        ]
        return self.type in endmill_types

    @property
    def is_drill(self) -> bool:
        """Check if tool is a drill."""
        drill_types = [
            ToolType.DRILL_TWIST,
            ToolType.DRILL_CENTER,
            ToolType.DRILL_SPOT,
            ToolType.DRILL_PECK,
            ToolType.DRILL_GUN
        ]
        return self.type in drill_types

    @property
    def needs_reorder(self) -> bool:
        """Check if tool needs reordering."""
        return self.quantity_available < self.minimum_stock

    @property
    def in_stock(self) -> bool:
        """Check if tool is in stock."""
        return self.quantity_available > 0

    @property
    def tool_radius(self) -> float | None:
        """Get tool radius in mm."""
        if not self.diameter_mm:
            return None
        return float(self.diameter_mm) / 2

    def consume(self, quantity: int = 1) -> bool:
        """Consume tool from inventory."""
        if self.quantity_available < quantity:
            return False
        self.quantity_available -= quantity
        return True

    def restock(self, quantity: int):
        """Add tools to inventory."""
        self.quantity_available += quantity

    def get_spec(self, key: str, default=None):
        """Get specific specification value."""
        if not self.specifications:
            return default
        return self.specifications.get(key, default)

    def set_spec(self, key: str, value):
        """Set specific specification value."""
        if not self.specifications:
            self.specifications = {}
        self.specifications[key] = value
