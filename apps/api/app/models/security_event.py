"""
Security event model for incident tracking.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Boolean, ForeignKey, Index,
    DateTime, Enum as SQLEnum, Text
)
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import SecurityEventType, SecuritySeverity


class SecurityEvent(Base, TimestampMixin):
    """Security-related events and incidents."""
    
    __tablename__ = "security_events"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Event type and severity
    event_type: Mapped[SecurityEventType] = mapped_column(
        SQLEnum(SecurityEventType),
        nullable=False,
        index=True
    )
    severity: Mapped[SecuritySeverity] = mapped_column(
        SQLEnum(SecuritySeverity),
        nullable=False,
        index=True
    )
    
    # Foreign keys
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True
    )
    resolved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    
    # Source information
    ip_address: Mapped[Optional[str]] = mapped_column(
        INET,
        index=True
    )
    
    # Event details
    details: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default={}
    )
    
    # Resolution status
    resolved: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    
    # Relationships
    user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="security_events",
        foreign_keys=[user_id]
    )
    resolver: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[resolved_by]
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_security_events_severity', 'severity',
              postgresql_where='resolved = false'),
        Index('idx_security_events_user_id', 'user_id',
              postgresql_where='user_id IS NOT NULL'),
        Index('idx_security_events_unresolved', 'created_at',
              postgresql_where='resolved = false'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<SecurityEvent(id={self.id}, type={self.event_type.value}, "
            f"severity={self.severity.value})>"
        )
    
    @property
    def is_critical(self) -> bool:
        """Check if event is critical severity."""
        return self.severity == SecuritySeverity.CRITICAL
    
    @property
    def is_high_severity(self) -> bool:
        """Check if event is high or critical severity."""
        return self.severity in [
            SecuritySeverity.HIGH,
            SecuritySeverity.CRITICAL
        ]
    
    @property
    def requires_immediate_action(self) -> bool:
        """Check if event requires immediate action."""
        critical_events = [
            SecurityEventType.DATA_BREACH,
            SecurityEventType.PRIVILEGE_ESCALATION,
            SecurityEventType.SQL_INJECTION,
            SecurityEventType.DDOS_DETECTED
        ]
        return (
            self.event_type in critical_events or
            self.is_critical
        ) and not self.resolved
    
    def resolve(self, resolver_id: int, notes: str = None):
        """Mark event as resolved."""
        self.resolved = True
        self.resolved_at = datetime.utcnow()
        self.resolved_by = resolver_id
        if notes:
            self.notes = notes
    
    def reopen(self, notes: str = None):
        """Reopen resolved event."""
        self.resolved = False
        self.resolved_at = None
        self.resolved_by = None
        if notes:
            if self.notes:
                self.notes += f"\n\nReopened: {notes}"
            else:
                self.notes = f"Reopened: {notes}"
    
    def add_detail(self, key: str, value):
        """Add detail to event."""
        if not self.details:
            self.details = {}
        self.details[key] = value
    
    def get_detail(self, key: str, default=None):
        """Get specific detail value."""
        if not self.details:
            return default
        return self.details.get(key, default)