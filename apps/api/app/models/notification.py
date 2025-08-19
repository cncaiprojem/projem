"""Notification model for user alerts and messages.

Enterprise-grade notification system with strict Task Master ERD compliance.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, ForeignKey, Index, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Notification(Base, TimestampMixin):
    """User notifications and alerts.

    Task Master ERD Compliance:
    - user_id FK with RESTRICT cascade behavior
    - type string field for notification classification
    - payload JSONB for notification data
    - read_at timestamp for read status tracking
    - Enterprise security and audit trail
    """

    __tablename__ = "notifications"

    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Foreign key with RESTRICT behavior per ERD
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT", name="fk_notifications_user_id"),
        nullable=False,
        index=True,
    )

    # Notification classification (Task Master ERD requirement)
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    # Notification data (Task Master ERD requirement)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=lambda: {})

    # Read status tracking (Task Master ERD requirement)
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User", back_populates="notifications", foreign_keys=[user_id]
    )

    # Enterprise-grade indexing strategy
    __table_args__ = (
        Index("idx_notifications_user_id_type", "user_id", "type"),
        Index(
            "idx_notifications_user_unread",
            "user_id",
            "created_at",
            postgresql_where="read_at IS NULL",
        ),
        Index("idx_notifications_type_created", "type", "created_at"),
        Index("idx_notifications_read_at", "read_at", postgresql_where="read_at IS NOT NULL"),
    )

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        status = "read" if self.read_at else "unread"
        return (
            f"<Notification(id={self.id}, user_id={self.user_id}, "
            f"type={self.type}, status={status})>"
        )

    def __str__(self) -> str:
        """User-friendly representation."""
        status = "okunmuş" if self.read_at else "okunmamış"
        return f"Bildirim #{self.id} - {self.type} ({status})"

    @property
    def is_read(self) -> bool:
        """Check if notification has been read."""
        return self.read_at is not None

    @property
    def is_unread(self) -> bool:
        """Check if notification is unread."""
        return self.read_at is None

    @property
    def title(self) -> Optional[str]:
        """Get notification title from payload."""
        return self.get_payload("title")

    @property
    def message(self) -> Optional[str]:
        """Get notification message from payload."""
        return self.get_payload("message")

    @property
    def priority(self) -> str:
        """Get notification priority from payload."""
        return self.get_payload("priority", "normal")

    def get_payload(self, key: str, default=None):
        """Get payload value safely."""
        if not self.payload:
            return default
        return self.payload.get(key, default)

    def set_payload(self, key: str, value) -> None:
        """Set payload value safely."""
        if self.payload is None:
            self.payload = {}
        self.payload[key] = value

    def mark_as_read(self) -> None:
        """Mark notification as read."""
        if not self.is_read:
            self.read_at = datetime.now(timezone.utc)

    def mark_as_unread(self) -> None:
        """Mark notification as unread."""
        self.read_at = None

    def create_job_notification(
        self, title: str, message: str, job_id: int, priority: str = "normal"
    ) -> None:
        """Create a job-related notification payload."""
        self.set_payload("title", title)
        self.set_payload("message", message)
        self.set_payload("job_id", job_id)
        self.set_payload("priority", priority)
        self.set_payload("created_at", datetime.now(timezone.utc).isoformat())

    def create_system_notification(
        self, title: str, message: str, category: str, priority: str = "normal"
    ) -> None:
        """Create a system notification payload."""
        self.set_payload("title", title)
        self.set_payload("message", message)
        self.set_payload("category", category)
        self.set_payload("priority", priority)
        self.set_payload("created_at", datetime.now(timezone.utc).isoformat())
