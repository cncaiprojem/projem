"""
Notification model for user alerts and messages.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    String, Boolean, ForeignKey, Index,
    DateTime, Enum as SQLEnum, Text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import NotificationType, NotificationSeverity


class Notification(Base, TimestampMixin):
    """User notifications and alerts."""
    
    __tablename__ = "notifications"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Foreign keys
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Notification type and severity
    type: Mapped[NotificationType] = mapped_column(
        SQLEnum(NotificationType),
        nullable=False
    )
    severity: Mapped[NotificationSeverity] = mapped_column(
        SQLEnum(NotificationSeverity),
        nullable=False,
        default=NotificationSeverity.INFO
    )
    
    # Content
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )
    message: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )
    
    # Additional data
    data: Mapped[Optional[dict]] = mapped_column(JSONB)
    
    # Read status
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    
    # Action URL
    action_url: Mapped[Optional[str]] = mapped_column(String(1024))
    
    # Expiration
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        index=True
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="notifications")
    
    # Indexes
    __table_args__ = (
        Index('idx_notifications_user_id_unread', 'user_id', 'created_at',
              postgresql_where='is_read = false'),
        Index('idx_notifications_expires_at', 'expires_at',
              postgresql_where='expires_at IS NOT NULL'),
        Index('idx_notifications_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, type={self.type.value}, user_id={self.user_id})>"
    
    @property
    def is_expired(self) -> bool:
        """Check if notification has expired."""
        if not self.expires_at:
            return False
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_actionable(self) -> bool:
        """Check if notification has an action."""
        return bool(self.action_url)
    
    def mark_as_read(self):
        """Mark notification as read."""
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.now(timezone.utc)
    
    def mark_as_unread(self):
        """Mark notification as unread."""
        self.is_read = False
        self.read_at = None
    
    def get_data(self, key: str, default=None):
        """Get specific data value."""
        if not self.data:
            return default
        return self.data.get(key, default)