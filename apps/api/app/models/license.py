"""
License model for Task 4.1: Ultra-enterprise license domain with state transitions.
Banking-grade implementation with Turkish KVKV compliance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, String, Text,
    ForeignKey, Index, text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm.attributes import flag_modified

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .user import User
    from .license_audit import LicenseAudit
    from .invoice import Invoice


class License(Base, TimestampMixin):
    """Ultra-enterprise license domain model with state transitions and auditability.
    
    Task 4.1 Implementation:
    - Supports 3m, 6m, 12m license durations
    - JSONB scope for flexible feature configuration
    - State machine for assign/extend/cancel/expire
    - Banking-grade constraints and indexing
    - Turkish KVKV compliance ready
    """
    
    __tablename__ = "licenses"
    
    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger, 
        primary_key=True, 
        autoincrement=True,
        comment="Unique license identifier"
    )
    
    # Foreign keys with enterprise security
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="User who owns this license"
    )
    
    # License type - Task 4.1 specific: 3m, 6m, 12m durations
    type: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="License duration type: 3m, 6m, or 12m"
    )
    
    # Flexible scope configuration (JSONB for feature flags, limits, etc.)
    scope: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'"),
        comment="License scope: features, limits, permissions as JSONB"
    )
    
    # License status with state machine
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
        comment="License status: active, expired, canceled"
    )
    
    # Cancellation reason (nullable for active/expired licenses)
    reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Reason for cancellation (if canceled)"
    )
    
    # Validity period with timezone awareness
    starts_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="License start timestamp (UTC)"
    )
    
    ends_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="License expiry timestamp (UTC)"
    )
    
    # Cancellation timestamp (nullable for non-canceled licenses)
    canceled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When license was canceled (if applicable)"
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User", 
        back_populates="licenses",
        lazy="select"
    )
    
    # Audit relationship
    audit_logs: Mapped[list["LicenseAudit"]] = relationship(
        "LicenseAudit",
        back_populates="license",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="desc(LicenseAudit.created_at)"
    )
    
    # Invoice relationship - Task 4.4
    invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice",
        back_populates="license",
        lazy="select",
        order_by="desc(Invoice.issued_at)"
    )
    
    # Ultra-enterprise constraints and indexes
    __table_args__ = (
        # Task 4.1 requirement: One active license per user
        # Partial unique index ensures only one active license per user at any time
        Index(
            'uq_licenses_one_active_per_user',
            'user_id',
            unique=True,
            postgresql_where=text("status = 'active' AND ends_at > CURRENT_TIMESTAMP")
        ),
        
        # License type validation
        CheckConstraint(
            "type IN ('3m', '6m', '12m')",
            name='ck_licenses_valid_type'
        ),
        
        # Status validation
        CheckConstraint(
            "status IN ('active', 'expired', 'canceled')",
            name='ck_licenses_valid_status'
        ),
        
        # Validity period constraint
        CheckConstraint(
            'ends_at > starts_at',
            name='ck_licenses_valid_period'
        ),
        
        # Cancellation logic constraints
        CheckConstraint(
            "(status != 'canceled' OR canceled_at IS NOT NULL)",
            name='ck_licenses_canceled_has_timestamp'
        ),
        CheckConstraint(
            "(status != 'canceled' OR reason IS NOT NULL)",
            name='ck_licenses_canceled_has_reason'
        ),
        CheckConstraint(
            "(status = 'canceled' OR (canceled_at IS NULL AND reason IS NULL))",
            name='ck_licenses_non_canceled_no_cancel_fields'
        ),
        
        # Performance indexes as per Task 4.1
        Index('idx_licenses_status_ends_at', 'status', 'ends_at'),
        Index('idx_licenses_user_status', 'user_id', 'status'),
        Index(
            'idx_licenses_active_expiring',
            'ends_at',
            postgresql_where=text("status = 'active'")
        ),
        
        # JSONB index for scope queries
        Index(
            'idx_licenses_scope',
            'scope',
            postgresql_using='gin'
        ),
    )
    
    def __repr__(self) -> str:
        return f"<License(id={self.id}, type={self.type}, status={self.status}, user_id={self.user_id})>"
    
    def __str__(self) -> str:
        return f"License {self.id}: {self.type} ({self.status})"
    
    @property
    def is_active(self) -> bool:
        """Check if license is currently active."""
        now = datetime.now(timezone.utc)
        return (
            self.status == 'active' and
            self.starts_at <= now < self.ends_at
        )
    
    @property
    def is_expired(self) -> bool:
        """Check if license has expired."""
        now = datetime.now(timezone.utc)
        return now >= self.ends_at
    
    @property
    def days_remaining(self) -> int:
        """Calculate days remaining until expiration."""
        if not self.is_active:
            return 0
        delta = self.ends_at - datetime.now(timezone.utc)
        return max(0, delta.days)
    
    @property
    def duration_months(self) -> int:
        """Get license duration in months based on type."""
        duration_map = {'3m': 3, '6m': 6, '12m': 12}
        return duration_map.get(self.type, 0)
    
    def has_feature(self, feature: str) -> bool:
        """Check if license scope includes specific feature."""
        if not self.is_active:
            return False
        
        # Check scope JSONB for feature
        if isinstance(self.scope, dict):
            return self.scope.get(feature, False)
        return False
    
    def get_limit(self, limit_key: str, default: int = 0) -> int:
        """Get numeric limit from license scope."""
        if not self.is_active:
            return 0
        
        if isinstance(self.scope, dict) and 'limits' in self.scope:
            return self.scope['limits'].get(limit_key, default)
        return default
    
    def can_extend(self) -> bool:
        """Check if license can be extended (Task 4.1 state transition rule)."""
        now = datetime.now(timezone.utc)
        return self.status == 'active' and self.ends_at >= now
    
    def can_cancel(self) -> bool:
        """Check if license can be canceled."""
        return self.status == 'active'
    
    def update_scope(self, key: str, value: any) -> None:
        """Update license scope with new feature/limit."""
        if self.scope is None:
            self.scope = {}
        self.scope[key] = value
        # Mark JSONB field as modified for SQLAlchemy tracking
        flag_modified(self, "scope")