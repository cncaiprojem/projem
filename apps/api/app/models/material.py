"""
Material model for machining material database.
"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String, Integer, Index,
    Numeric, CheckConstraint, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin
from .enums import MaterialCategory


class Material(Base, TimestampMixin):
    """Material database for machining."""
    
    __tablename__ = "materials"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Material identification
    category: Mapped[MaterialCategory] = mapped_column(
        SQLEnum(MaterialCategory),
        nullable=False,
        index=True
    )
    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True
    )
    grade: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Physical properties
    density_g_cm3: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 3)
    )
    hardness_hb: Mapped[Optional[int]] = mapped_column(Integer)
    tensile_strength_mpa: Mapped[Optional[int]] = mapped_column(Integer)
    
    # Machining properties
    machinability_rating: Mapped[Optional[int]] = mapped_column(Integer)
    cutting_speed_m_min: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2)
    )
    feed_rate_mm_tooth: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 4)
    )
    
    # Additional properties
    properties: Mapped[Optional[dict]] = mapped_column(JSONB)
    
    # Cost information
    cost_per_kg: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2)
    )
    supplier: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Constraints and indexes
    __table_args__ = (
        CheckConstraint('density_g_cm3 > 0',
                       name='ck_materials_density_positive'),
        CheckConstraint('hardness_hb > 0',
                       name='ck_materials_hardness_positive'),
        CheckConstraint('tensile_strength_mpa > 0',
                       name='ck_materials_tensile_positive'),
        CheckConstraint('machinability_rating >= 0 AND machinability_rating <= 100',
                       name='ck_materials_machinability_valid'),
        CheckConstraint('cutting_speed_m_min > 0',
                       name='ck_materials_cutting_speed_positive'),
        CheckConstraint('feed_rate_mm_tooth > 0',
                       name='ck_materials_feed_rate_positive'),
        CheckConstraint('cost_per_kg >= 0',
                       name='ck_materials_cost_non_negative'),
        Index('idx_materials_properties', 'properties',
              postgresql_using='gin',
              postgresql_where='properties IS NOT NULL'),
    )
    
    def __repr__(self) -> str:
        return f"<Material(id={self.id}, name={self.name}, category={self.category.value})>"
    
    @property
    def is_metal(self) -> bool:
        """Check if material is a metal."""
        metal_categories = [
            MaterialCategory.STEEL_CARBON,
            MaterialCategory.STEEL_ALLOY,
            MaterialCategory.STEEL_STAINLESS,
            MaterialCategory.STEEL_TOOL,
            MaterialCategory.ALUMINUM,
            MaterialCategory.TITANIUM,
            MaterialCategory.COPPER,
            MaterialCategory.BRASS,
            MaterialCategory.BRONZE,
            MaterialCategory.CAST_IRON,
            MaterialCategory.NICKEL,
            MaterialCategory.MAGNESIUM
        ]
        return self.category in metal_categories
    
    @property
    def is_plastic(self) -> bool:
        """Check if material is a plastic."""
        plastic_categories = [
            MaterialCategory.PLASTIC_SOFT,
            MaterialCategory.PLASTIC_HARD,
            MaterialCategory.PLASTIC_FIBER
        ]
        return self.category in plastic_categories
    
    @property
    def is_wood(self) -> bool:
        """Check if material is wood."""
        wood_categories = [
            MaterialCategory.WOOD_SOFT,
            MaterialCategory.WOOD_HARD,
            MaterialCategory.WOOD_MDF
        ]
        return self.category in wood_categories
    
    def get_property(self, key: str, default=None):
        """Get specific property value."""
        if not self.properties:
            return default
        return self.properties.get(key, default)
    
    def calculate_weight(self, volume_cm3: float) -> Optional[float]:
        """Calculate weight in kg for given volume."""
        if not self.density_g_cm3:
            return None
        weight_g = float(self.density_g_cm3) * volume_cm3
        return weight_g / 1000  # Convert to kg