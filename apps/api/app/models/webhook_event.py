"""
Webhook event model for deduplication and reliable delivery.
Task 4.11: Ensures exactly-once webhook processing semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .user import User


class WebhookEvent(Base, TimestampMixin):
    """Track webhook events for deduplication and retry management.
    
    ENTERPRISE DESIGN PRINCIPLES:
    - Unique event_id prevents duplicate processing
    - Retry tracking with exponential backoff
    - Delivery confirmation and audit trail
    - Dead letter queue for failed webhooks
    """

    __tablename__ = "webhook_events"

    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # Unique event identifier (from source system)
    event_id: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True,
        comment="Unique event identifier for deduplication"
    )

    # Event metadata
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Type of webhook event (e.g., license.expired, payment.completed)"
    )

    # Source entity reference
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of entity (e.g., license, invoice, payment)"
    )

    entity_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        index=True,
        comment="ID of the related entity"
    )

    # Optional user association
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="Associated user (if applicable)"
    )

    # Webhook endpoint
    webhook_url: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="Target webhook URL"
    )

    # Payload
    payload: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Webhook payload data"
    )

    # Delivery status
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
        comment="Delivery status: pending, processing, delivered, failed"
    )

    # Retry tracking
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Number of delivery attempts"
    )

    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=5,
        comment="Maximum number of retry attempts"
    )

    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When to attempt next delivery"
    )

    # Delivery confirmation
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When webhook was successfully delivered"
    )

    # Response tracking
    last_response_status: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="HTTP status code of last delivery attempt"
    )

    last_response_body: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Response body from last delivery attempt"
    )

    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error message from last failed attempt"
    )

    # Processing lock (for concurrent workers)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When event was locked for processing"
    )

    locked_by: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Worker ID that locked this event"
    )

    # Relationships
    user: Mapped[User | None] = relationship(
        "User",
        back_populates="webhook_events",
        lazy="select"
    )

    __table_args__ = (
        # Unique event ID for deduplication
        UniqueConstraint(
            "event_id",
            name="uq_webhook_events_event_id"
        ),

        # Index for finding events to process
        Index(
            "idx_webhook_events_pending",
            "status", "next_retry_at",
            postgresql_where="status IN ('pending', 'failed') AND retry_count < max_retries"
        ),

        # Index for entity lookups
        Index(
            "idx_webhook_events_entity",
            "entity_type", "entity_id"
        ),

        # Index for lock cleanup
        Index(
            "idx_webhook_events_locked",
            "locked_at", "locked_by",
            postgresql_where="locked_at IS NOT NULL"
        ),
    )

    def __repr__(self) -> str:
        return f"<WebhookEvent(id={self.id}, event_id='{self.event_id}', type='{self.event_type}')>"

    @classmethod
    def create_event(
        cls,
        event_id: str,
        event_type: str,
        entity_type: str,
        entity_id: int,
        webhook_url: str,
        payload: dict,
        user_id: int | None = None
    ) -> WebhookEvent:
        """Create a new webhook event."""
        return cls(
            event_id=event_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            webhook_url=webhook_url,
            payload=payload,
            status="pending"
        )

    def should_retry(self) -> bool:
        """Check if this event should be retried."""
        return (
            self.status in ["pending", "failed"] and
            self.retry_count < self.max_retries
        )

    def calculate_next_retry(self) -> datetime:
        """Calculate next retry time with exponential backoff."""
        # Exponential backoff: 1, 2, 4, 8, 16 minutes
        delay_minutes = min(2 ** self.retry_count, 60)
        return datetime.now(UTC) + timedelta(minutes=delay_minutes)

    def mark_delivered(self, response_status: int, response_body: str = None) -> None:
        """Mark webhook as successfully delivered."""
        self.status = "delivered"
        self.delivered_at = datetime.now(UTC)
        self.last_response_status = response_status
        self.last_response_body = response_body
        self.locked_at = None
        self.locked_by = None

    def mark_failed(self, error: str, response_status: int = None) -> None:
        """Mark delivery attempt as failed."""
        self.retry_count += 1
        self.last_error = error
        self.last_response_status = response_status

        if self.retry_count >= self.max_retries:
            self.status = "failed"
        else:
            self.status = "pending"
            self.next_retry_at = self.calculate_next_retry()

        self.locked_at = None
        self.locked_by = None

    def acquire_lock(self, worker_id: str, lock_timeout_seconds: int = 300) -> bool:
        """Try to acquire processing lock."""
        now = datetime.now(UTC)

        # Check if already locked by another worker
        if self.locked_at and self.locked_by != worker_id:
            lock_age = (now - self.locked_at).total_seconds()
            if lock_age < lock_timeout_seconds:
                return False  # Still locked by another worker

        # Acquire lock
        self.locked_at = now
        self.locked_by = worker_id
        return True

    def release_lock(self) -> None:
        """Release processing lock."""
        self.locked_at = None
        self.locked_by = None
