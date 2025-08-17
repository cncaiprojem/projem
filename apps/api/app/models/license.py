"""
License model for subscription and feature management.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    String, Integer, Boolean, ForeignKey, 
    Index, DateTime, CheckConstraint, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import LicenseType, LicenseStatus


class License(Base, TimestampMixin):
    """Software licensing and subscription management."""
    
    __tablename__ = "licenses"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Foreign keys
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    
    # License details
    type: Mapped[LicenseType] = mapped_column(
        SQLEnum(LicenseType),
        nullable=False
    )
    status: Mapped[LicenseStatus] = mapped_column(
        SQLEnum(LicenseStatus),
        nullable=False,
        index=True
    )
    
    # Capacity
    seats: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1
    )
    
    # Features configuration
    features: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default={}
    )
    
    # Validity period
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False
    )
    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True
    )
    
    # Renewal settings
    auto_renew: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="licenses")
    
    # Constraints and indexes
    __table_args__ = (
        CheckConstraint('seats > 0', name='ck_licenses_seats_positive'),
        CheckConstraint('ends_at > starts_at', name='ck_licenses_valid_period'),
        Index('idx_licenses_status', 'status',
              postgresql_where="status = 'active'"),
        Index('idx_licenses_ends_at', 'ends_at',
              postgresql_where="status = 'active'"),
        Index('idx_licenses_features', 'features',
              postgresql_using='gin'),
    )
    
    def __repr__(self) -> str:
        return f"<License(id={self.id}, type={self.type.value}, status={self.status.value})>"
    
    @property
    def is_active(self) -> bool:
        """Check if license is currently active."""
        now = datetime.now(timezone.utc)
        return (
            self.status == LicenseStatus.ACTIVE and
            self.starts_at <= now <= self.ends_at
        )
    
    @property
    def days_remaining(self) -> int:
        """Calculate days remaining until expiration."""
        if not self.is_active:
            return 0
        delta = self.ends_at - datetime.now(timezone.utc)
        return max(0, delta.days)
    
    def has_feature(self, feature: str) -> bool:
        """Check if license includes specific feature."""
        if not self.is_active:
            return False
        
        # Check if feature is explicitly enabled
        if feature in self.features:
            return bool(self.features[feature])
        
        # Check default features by license type
        default_features = {
            LicenseType.TRIAL: {
                'cad_basic': True,
                'cam_basic': True,
                'simulation_basic': True,
                'max_jobs': 10,
                'max_models': 50
            },
            LicenseType.BASIC: {
                'cad_basic': True,
                'cam_basic': True,
                'simulation_basic': True,
                'max_jobs': 100,
                'max_models': 500
            },
            LicenseType.PROFESSIONAL: {
                'cad_basic': True,
                'cad_advanced': True,
                'cam_basic': True,
                'cam_advanced': True,
                'simulation_basic': True,
                'simulation_advanced': True,
                'max_jobs': 1000,
                'max_models': 5000
            },
            LicenseType.ENTERPRISE: {
                'cad_basic': True,
                'cad_advanced': True,
                'cam_basic': True,
                'cam_advanced': True,
                'simulation_basic': True,
                'simulation_advanced': True,
                'api_access': True,
                'erp_integration': True,
                'max_jobs': -1,  # Unlimited
                'max_models': -1  # Unlimited
            }
        }
        
        type_features = default_features.get(self.type, {})
        return type_features.get(feature, False)