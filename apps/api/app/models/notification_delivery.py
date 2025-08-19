"""
Notification delivery model for Task 4.7 - Core notification tracking.
Ultra-enterprise notification system with provider fallback and audit trail.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import NotificationChannel, NotificationProvider, NotificationStatus

if TYPE_CHECKING:
    from .user import User
    from .license import License
    from .notification_template import NotificationTemplate
    from .notification_attempt import NotificationAttempt


class NotificationDelivery(Base, TimestampMixin):
    """Core notification delivery tracking with provider fallback.

    Task 4.7 Implementation:
    - Email/SMS notification tracking with status management
    - Provider fallback support (primary -> fallback)
    - License reminder scheduling (D-7, D-3, D-1)
    - Template-based content rendering
    - Retry logic with exponential backoff
    - Turkish KVKK compliance for communication preferences
    """

    __tablename__ = "notifications_delivery"

    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="Unique notification identifier"
    )

    # Foreign keys with RESTRICT behavior for data integrity
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="User receiving this notification",
    )

    license_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("licenses.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Associated license (null for non-license notifications)",
    )

    template_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notification_templates.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Template used for content generation",
    )

    # Notification metadata
    channel: Mapped[NotificationChannel] = mapped_column(
        nullable=False, index=True, comment="Delivery channel: email or SMS"
    )

    recipient: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="Email address or phone number"
    )

    days_out: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="Days remaining for license reminders (7, 3, 1)"
    )

    # Rendered content
    subject: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, comment="Rendered subject (null for SMS)"
    )

    body: Mapped[str] = mapped_column(Text, nullable=False, comment="Rendered message body")

    variables: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}", comment="Template variables used for rendering"
    )

    # Delivery tracking
    status: Mapped[NotificationStatus] = mapped_column(
        nullable=False, server_default="queued", index=True, comment="Current delivery status"
    )

    priority: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        server_default="normal",
        comment="Priority: low, normal, high, urgent",
    )

    scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When to send (null for immediate)"
    )

    # Provider and external tracking
    primary_provider: Mapped[NotificationProvider] = mapped_column(
        nullable=False, comment="Primary provider to attempt"
    )

    actual_provider: Mapped[Optional[NotificationProvider]] = mapped_column(
        nullable=True, comment="Provider that actually sent (may differ due to fallback)"
    )

    provider_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True, comment="Provider-specific message ID for tracking"
    )

    provider_response: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, comment="Full provider response for debugging"
    )

    # Error handling and retry logic
    error_code: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True, comment="Error code for failed deliveries"
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Detailed error message"
    )

    retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="Current retry attempt count"
    )

    max_retries: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="3", comment="Maximum retry attempts allowed"
    )

    # Timing tracking
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When notification was sent to provider",
    )

    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When notification was delivered to recipient",
    )

    failed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When notification failed permanently",
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User", back_populates="notification_deliveries", lazy="select"
    )

    license: Mapped[Optional["License"]] = relationship("License", lazy="select")

    template: Mapped["NotificationTemplate"] = relationship(
        "NotificationTemplate", back_populates="notifications", lazy="select"
    )

    attempts: Mapped[list["NotificationAttempt"]] = relationship(
        "NotificationAttempt",
        back_populates="notification",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="NotificationAttempt.attempt_number",
    )

    # Ultra-enterprise constraints and indexes
    __table_args__ = (
        # Priority validation
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_notifications_delivery_valid_priority",
        ),
        # License reminder days validation
        CheckConstraint(
            "days_out IN (1, 3, 7) OR days_out IS NULL",
            name="ck_notifications_delivery_valid_days_out",
        ),
        # Retry count must not exceed max
        CheckConstraint("retry_count <= max_retries", name="ck_notifications_delivery_retry_limit"),
        # SMS cannot have subject
        CheckConstraint(
            "(channel = 'sms' AND subject IS NULL) OR channel = 'email'",
            name="ck_notifications_delivery_sms_no_subject",
        ),
        # Sent status must have timestamp
        CheckConstraint(
            "(status = 'sent' AND sent_at IS NOT NULL) OR status != 'sent'",
            name="ck_notifications_delivery_sent_has_timestamp",
        ),
        # Failed status must have timestamp
        CheckConstraint(
            "(status = 'failed' AND failed_at IS NOT NULL) OR status != 'failed'",
            name="ck_notifications_delivery_failed_has_timestamp",
        ),
        # Performance and analytics indexes
        Index("idx_notifications_delivery_user_status", "user_id", "status"),
        Index("idx_notifications_delivery_license_channel", "license_id", "channel"),
        Index(
            "idx_notifications_delivery_scheduled",
            "scheduled_at",
            postgresql_where="status = 'queued' AND scheduled_at IS NOT NULL",
        ),
        Index(
            "idx_notifications_delivery_failed_retry",
            "status",
            "retry_count",
            postgresql_where="status = 'failed' AND retry_count < max_retries",
        ),
        Index(
            "idx_notifications_delivery_provider_tracking", "provider_message_id", "actual_provider"
        ),
        Index("idx_notifications_delivery_analytics", "channel", "status", "created_at"),
        Index("idx_notifications_delivery_variables", "variables", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return (
            f"<NotificationDelivery(id={self.id}, user_id={self.user_id}, "
            f"channel={self.channel.value}, status={self.status.value})>"
        )

    def __str__(self) -> str:
        return f"Notification #{self.id} to {self.recipient} ({self.status.value})"

    @property
    def is_email(self) -> bool:
        """Check if this is an email notification."""
        return self.channel == NotificationChannel.EMAIL

    @property
    def is_sms(self) -> bool:
        """Check if this is an SMS notification."""
        return self.channel == NotificationChannel.SMS

    @property
    def is_queued(self) -> bool:
        """Check if notification is queued for delivery."""
        return self.status == NotificationStatus.QUEUED

    @property
    def is_sent(self) -> bool:
        """Check if notification has been sent."""
        return self.status == NotificationStatus.SENT

    @property
    def is_delivered(self) -> bool:
        """Check if notification was delivered."""
        return self.status == NotificationStatus.DELIVERED

    @property
    def is_failed(self) -> bool:
        """Check if notification failed."""
        return self.status == NotificationStatus.FAILED

    @property
    def can_retry(self) -> bool:
        """Check if notification can be retried."""
        return self.status == NotificationStatus.FAILED and self.retry_count < self.max_retries

    @property
    def is_license_reminder(self) -> bool:
        """Check if this is a license reminder notification."""
        return self.days_out is not None

    def mark_as_sent(self, provider: NotificationProvider, message_id: str = None) -> None:
        """Mark notification as sent.

        Args:
            provider: Provider that sent the notification
            message_id: Provider-specific message ID
        """
        self.status = NotificationStatus.SENT
        self.actual_provider = provider
        self.provider_message_id = message_id
        self.sent_at = datetime.now(timezone.utc)
        self.error_code = None
        self.error_message = None

    def mark_as_delivered(self) -> None:
        """Mark notification as delivered."""
        self.status = NotificationStatus.DELIVERED
        self.delivered_at = datetime.now(timezone.utc)

    def mark_as_failed(self, error_code: str, error_message: str) -> None:
        """Mark notification as failed.

        Args:
            error_code: Error code
            error_message: Detailed error message
        """
        self.status = NotificationStatus.FAILED
        self.error_code = error_code
        self.error_message = error_message
        self.failed_at = datetime.now(timezone.utc)

    def mark_as_bounced(self, error_code: str, error_message: str) -> None:
        """Mark notification as bounced.

        Args:
            error_code: Bounce error code
            error_message: Bounce error message
        """
        self.status = NotificationStatus.BOUNCED
        self.error_code = error_code
        self.error_message = error_message
        self.failed_at = datetime.now(timezone.utc)

    def increment_retry_count(self) -> None:
        """Increment retry attempt counter."""
        self.retry_count += 1

    def set_provider_response(self, response: dict) -> None:
        """Set provider response data.

        Args:
            response: Provider response data
        """
        if self.provider_response is None:
            self.provider_response = {}
        self.provider_response.update(response)

    def schedule_for(self, send_time: datetime) -> None:
        """Schedule notification for specific time.

        Args:
            send_time: When to send the notification
        """
        self.scheduled_at = send_time
        self.status = NotificationStatus.QUEUED

    def is_due_for_sending(self) -> bool:
        """Check if notification is due for sending.

        Returns:
            True if notification should be sent now
        """
        if not self.is_queued:
            return False

        if self.scheduled_at is None:
            return True  # Send immediately

        return datetime.now(timezone.utc) >= self.scheduled_at

    @classmethod
    def create_license_reminder(
        cls,
        user_id: int,
        license_id: int,
        template_id: int,
        channel: NotificationChannel,
        recipient: str,
        days_out: int,
        variables: dict,
        rendered_content: dict,
        primary_provider: NotificationProvider,
        priority: str = "normal",
    ) -> "NotificationDelivery":
        """Create a license reminder notification.

        Args:
            user_id: User ID
            license_id: License ID
            template_id: Template ID
            channel: Delivery channel
            recipient: Email or phone
            days_out: Days until expiration
            variables: Template variables
            rendered_content: Rendered subject/body
            primary_provider: Primary provider to use
            priority: Notification priority

        Returns:
            Created notification instance
        """
        return cls(
            user_id=user_id,
            license_id=license_id,
            template_id=template_id,
            channel=channel,
            recipient=recipient,
            days_out=days_out,
            subject=rendered_content.get("subject"),
            body=rendered_content["body"],
            variables=variables,
            primary_provider=primary_provider,
            priority=priority,
            status=NotificationStatus.QUEUED,
        )

    @classmethod
    def get_pending_notifications(
        cls, db_session, limit: int = 100
    ) -> list["NotificationDelivery"]:
        """Get notifications ready for sending.

        Args:
            db_session: Database session
            limit: Maximum number of notifications

        Returns:
            List of pending notifications
        """
        now = datetime.now(timezone.utc)
        return (
            db_session.query(cls)
            .filter(
                cls.status == NotificationStatus.QUEUED,
                (cls.scheduled_at.is_(None) | (cls.scheduled_at <= now)),
            )
            .order_by(cls.priority.desc(), cls.created_at)
            .limit(limit)
            .all()
        )

    @classmethod
    def get_failed_retryable(cls, db_session, limit: int = 50) -> list["NotificationDelivery"]:
        """Get failed notifications that can be retried.

        Args:
            db_session: Database session
            limit: Maximum number of notifications

        Returns:
            List of retryable failed notifications
        """
        return (
            db_session.query(cls)
            .filter(cls.status == NotificationStatus.FAILED, cls.retry_count < cls.max_retries)
            .order_by(cls.failed_at)
            .limit(limit)
            .all()
        )
