"""
Notification attempt model for Task 4.7 - Provider attempt audit trail.
Ultra-enterprise audit system for tracking all notification delivery attempts.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import NotificationProvider, NotificationStatus

if TYPE_CHECKING:
    from .notification_delivery import NotificationDelivery


class NotificationAttempt(Base):
    """Audit trail for notification delivery attempts with provider fallback tracking.
    
    Task 4.7 Implementation:
    - Complete audit trail of all delivery attempts
    - Provider fallback tracking (primary -> fallback)
    - Request/response logging for debugging
    - Performance metrics and timing
    - Error classification for analytics
    """
    
    __tablename__ = "notification_attempts"
    
    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Unique attempt identifier"
    )
    
    # Foreign key to main notification
    notification_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("notifications_delivery.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Associated notification delivery"
    )
    
    # Attempt metadata
    attempt_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="Sequential attempt number (1, 2, 3, etc.)"
    )
    
    provider: Mapped[NotificationProvider] = mapped_column(
        nullable=False,
        comment="Provider used for this attempt"
    )
    
    status: Mapped[NotificationStatus] = mapped_column(
        nullable=False,
        index=True,
        comment="Result status of this attempt"
    )
    
    # Provider interaction details
    provider_request: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Request payload sent to provider"
    )
    
    provider_response: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Response received from provider"
    )
    
    provider_message_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Provider-specific message ID"
    )
    
    # Error details
    error_code: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Provider-specific error code"
    )
    
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Detailed error message"
    )
    
    http_status_code: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="HTTP status code from provider API"
    )
    
    # Timing metrics
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="CURRENT_TIMESTAMP",
        comment="When attempt started"
    )
    
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When attempt completed"
    )
    
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Attempt duration in milliseconds"
    )
    
    # Relationships
    notification: Mapped["NotificationDelivery"] = relationship(
        "NotificationDelivery",
        back_populates="attempts",
        lazy="select"
    )
    
    # Ultra-enterprise constraints and indexes
    __table_args__ = (
        # Attempt number must be positive
        CheckConstraint(
            "attempt_number >= 1",
            name='ck_notification_attempts_positive_attempt'
        ),
        
        # Completion consistency
        CheckConstraint(
            "(completed_at IS NOT NULL AND duration_ms IS NOT NULL) OR "
            "(completed_at IS NULL AND duration_ms IS NULL)",
            name='ck_notification_attempts_completion_consistency'
        ),
        
        # Valid HTTP status codes
        CheckConstraint(
            "http_status_code >= 100 AND http_status_code < 600 OR http_status_code IS NULL",
            name='ck_notification_attempts_valid_http_status'
        ),
        
        # Unique constraint: one attempt per notification + attempt_number
        UniqueConstraint(
            'notification_id', 'attempt_number',
            name='uq_notification_attempts_number'
        ),
        
        # Performance indexes
        Index('idx_notification_attempts_provider_status', 'provider', 'status'),
        Index('idx_notification_attempts_timing', 'started_at', 'completed_at'),
        Index(
            'idx_notification_attempts_errors',
            'error_code',
            postgresql_where="error_code IS NOT NULL"
        ),
    )
    
    def __repr__(self) -> str:
        return (
            f"<NotificationAttempt(id={self.id}, notification_id={self.notification_id}, "
            f"attempt={self.attempt_number}, provider={self.provider.value}, status={self.status.value})>"
        )
    
    def __str__(self) -> str:
        return f"Attempt #{self.attempt_number} via {self.provider.value} ({self.status.value})"
    
    @property
    def is_successful(self) -> bool:
        """Check if attempt was successful."""
        return self.status in (NotificationStatus.SENT, NotificationStatus.DELIVERED)
    
    @property
    def is_failed(self) -> bool:
        """Check if attempt failed."""
        return self.status in (NotificationStatus.FAILED, NotificationStatus.BOUNCED)
    
    @property
    def is_completed(self) -> bool:
        """Check if attempt has completed (success or failure)."""
        return self.completed_at is not None
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Get attempt duration in seconds."""
        if self.duration_ms is not None:
            return self.duration_ms / 1000.0
        return None
    
    def mark_as_started(self) -> None:
        """Mark attempt as started."""
        self.started_at = datetime.now(timezone.utc)
    
    def mark_as_completed(self, status: NotificationStatus) -> None:
        """Mark attempt as completed.
        
        Args:
            status: Final status of the attempt
        """
        now = datetime.now(timezone.utc)
        self.completed_at = now
        self.status = status
        
        # Calculate duration
        if self.started_at:
            delta = now - self.started_at
            self.duration_ms = int(delta.total_seconds() * 1000)
    
    def set_provider_request(self, request_data: dict) -> None:
        """Set provider request data.
        
        Args:
            request_data: Request payload sent to provider
        """
        self.provider_request = request_data
    
    def set_provider_response(
        self,
        response_data: dict,
        message_id: str = None,
        http_status: int = None
    ) -> None:
        """Set provider response data.
        
        Args:
            response_data: Response received from provider
            message_id: Provider message ID
            http_status: HTTP status code
        """
        self.provider_response = response_data
        if message_id:
            self.provider_message_id = message_id
        if http_status:
            self.http_status_code = http_status
    
    def set_error(self, error_code: str, error_message: str) -> None:
        """Set error information.
        
        Args:
            error_code: Provider-specific error code
            error_message: Detailed error message
        """
        self.error_code = error_code
        self.error_message = error_message
    
    @classmethod
    def create_attempt(
        cls,
        notification_id: int,
        attempt_number: int,
        provider: NotificationProvider
    ) -> "NotificationAttempt":
        """Create a new notification attempt.
        
        Args:
            notification_id: Associated notification ID
            attempt_number: Sequential attempt number
            provider: Provider for this attempt
            
        Returns:
            Created attempt instance
        """
        return cls(
            notification_id=notification_id,
            attempt_number=attempt_number,
            provider=provider,
            status=NotificationStatus.QUEUED  # Initial status
        )
    
    @classmethod
    def get_attempt_stats(cls, db_session, hours: int = 24) -> dict:
        """Get attempt statistics for monitoring.
        
        Args:
            db_session: Database session
            hours: Hours to look back
            
        Returns:
            Statistics dictionary
        """
        from sqlalchemy import and_, func
        
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        # Get overall stats
        total_attempts = db_session.query(func.count(cls.id)).filter(
            cls.started_at >= since
        ).scalar()
        
        successful_attempts = db_session.query(func.count(cls.id)).filter(
            and_(
                cls.started_at >= since,
                cls.status.in_([NotificationStatus.SENT, NotificationStatus.DELIVERED])
            )
        ).scalar()
        
        failed_attempts = db_session.query(func.count(cls.id)).filter(
            and_(
                cls.started_at >= since,
                cls.status.in_([NotificationStatus.FAILED, NotificationStatus.BOUNCED])
            )
        ).scalar()
        
        # Get provider stats
        provider_stats = db_session.query(
            cls.provider,
            func.count(cls.id).label('count'),
            func.avg(cls.duration_ms).label('avg_duration_ms')
        ).filter(
            cls.started_at >= since
        ).group_by(cls.provider).all()
        
        # Get error distribution
        error_stats = db_session.query(
            cls.error_code,
            func.count(cls.id).label('count')
        ).filter(
            and_(
                cls.started_at >= since,
                cls.error_code.is_not(None)
            )
        ).group_by(cls.error_code).order_by(func.count(cls.id).desc()).limit(10).all()
        
        return {
            'total_attempts': total_attempts or 0,
            'successful_attempts': successful_attempts or 0,
            'failed_attempts': failed_attempts or 0,
            'success_rate': (successful_attempts / total_attempts * 100) if total_attempts else 0,
            'provider_stats': [
                {
                    'provider': stat.provider.value,
                    'count': stat.count,
                    'avg_duration_ms': float(stat.avg_duration_ms) if stat.avg_duration_ms else 0
                }
                for stat in provider_stats
            ],
            'top_errors': [
                {'error_code': stat.error_code, 'count': stat.count}
                for stat in error_stats
            ]
        }