"""
Magic Link model for Task 3.6 ultra enterprise passwordless authentication.

This model implements banking-level security for magic link token tracking:
- Single-use enforcement with database-backed consumption tracking
- 15-minute cryptographic expiration with secure nonce generation
- IP address and device fingerprint audit logging
- Complete audit trail for security monitoring
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Index, String, Text
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class MagicLink(Base, TimestampMixin):
    """Magic link token model with ultra enterprise security."""

    __tablename__ = "magic_links"

    # Primary key
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="Unique magic link ID"
    )

    # Target email (may or may not correspond to existing user)
    email: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Target email address for magic link"
    )

    # Security nonce for single-use enforcement
    nonce: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment="Cryptographically secure nonce for single-use enforcement"
    )

    # Token issuance tracking
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
        comment="Token issuance timestamp"
    )

    # Token consumption tracking
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Token consumption timestamp"
    )

    # Security audit fields
    ip_address: Mapped[str | None] = mapped_column(
        INET,
        nullable=True,
        comment="IP address of token request"
    )

    user_agent: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="User agent of token request"
    )

    # Device fingerprint for security correlation
    device_fingerprint: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Device fingerprint for consumption verification"
    )

    # Consumption audit fields
    consumed_ip_address: Mapped[str | None] = mapped_column(
        INET,
        nullable=True,
        comment="IP address of token consumption"
    )

    consumed_user_agent: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="User agent of token consumption"
    )

    consumed_device_fingerprint: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,
        comment="Device fingerprint of token consumption"
    )

    # Invalidation tracking
    invalidated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Token invalidation timestamp"
    )

    invalidation_reason: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Reason for token invalidation"
    )

    # Attempt tracking for security monitoring
    consumption_attempts: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        comment="Number of consumption attempts"
    )

    # Security metadata
    security_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional security metadata as JSON"
    )

    # Indexes and constraints
    __table_args__ = (
        # Security indexes
        Index('idx_magic_links_email_issued', 'email', 'issued_at'),
        Index('idx_magic_links_nonce_unique', 'nonce', unique=True),
        Index('idx_magic_links_issued_at', 'issued_at'),
        Index('idx_magic_links_consumed_at', 'consumed_at',
              postgresql_where='consumed_at IS NOT NULL'),
        Index('idx_magic_links_ip_address', 'ip_address',
              postgresql_where='ip_address IS NOT NULL'),
        Index('idx_magic_links_active', 'email', 'issued_at',
              postgresql_where='consumed_at IS NULL AND invalidated_at IS NULL'),

        # Performance indexes for cleanup operations
        Index('idx_magic_links_expired', 'issued_at',
              postgresql_where='consumed_at IS NULL AND invalidated_at IS NULL'),

        # Security constraints
        CheckConstraint(
            'consumption_attempts >= 0',
            name='ck_magic_links_consumption_attempts_non_negative'
        ),
        CheckConstraint(
            'consumed_at IS NULL OR consumed_at >= issued_at',
            name='ck_magic_links_consumed_after_issued'
        ),
        CheckConstraint(
            'invalidated_at IS NULL OR invalidated_at >= issued_at',
            name='ck_magic_links_invalidated_after_issued'
        ),
        CheckConstraint(
            "invalidation_reason IS NULL OR invalidation_reason IN ('expired', 'consumed', 'security_revoked', 'admin_revoked')",
            name='ck_magic_links_invalidation_reason_valid'
        ),
    )

    def __repr__(self) -> str:
        return f"<MagicLink(id={self.id}, email={self.email}, issued_at={self.issued_at})>"

    @property
    def is_expired(self) -> bool:
        """Check if magic link has expired (15 minutes from issuance)."""
        if self.invalidated_at:
            return True

        expiry_time = self.issued_at + timedelta(minutes=15)
        return datetime.now(UTC) > expiry_time

    @property
    def is_consumed(self) -> bool:
        """Check if magic link has been consumed."""
        return self.consumed_at is not None

    @property
    def is_valid(self) -> bool:
        """Check if magic link is valid for consumption."""
        return not self.is_expired and not self.is_consumed and not self.invalidated_at

    @property
    def expires_at(self) -> datetime:
        """Get expiration timestamp."""
        return self.issued_at + timedelta(minutes=15)

    @property
    def remaining_seconds(self) -> int:
        """Get remaining seconds before expiration."""
        if self.is_expired:
            return 0

        remaining = self.expires_at - datetime.now(UTC)
        return max(0, int(remaining.total_seconds()))

    def consume(
        self,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_fingerprint: str | None = None
    ) -> None:
        """
        Mark magic link as consumed with audit information.
        
        Args:
            ip_address: IP address of consumption
            user_agent: User agent of consumption
            device_fingerprint: Device fingerprint of consumption
        """
        if not self.is_valid:
            raise ValueError("Cannot consume invalid magic link")

        self.consumed_at = datetime.now(UTC)
        self.consumed_ip_address = ip_address
        self.consumed_user_agent = user_agent
        self.consumed_device_fingerprint = device_fingerprint

    def invalidate(self, reason: str) -> None:
        """
        Invalidate magic link with reason.
        
        Args:
            reason: Invalidation reason
        """
        valid_reasons = ['expired', 'consumed', 'security_revoked', 'admin_revoked']
        if reason not in valid_reasons:
            raise ValueError(f"Invalid reason. Must be one of: {valid_reasons}")

        self.invalidated_at = datetime.now(UTC)
        self.invalidation_reason = reason

    def increment_attempt(self) -> None:
        """Increment consumption attempt counter for security monitoring."""
        self.consumption_attempts += 1

    def get_security_summary(self) -> dict[str, Any]:
        """Get security summary for audit logging."""
        return {
            'id': str(self.id),
            'email_hash': hash(self.email) % 1000000,  # Masked email for logs
            'issued_at': self.issued_at.isoformat(),
            'consumed_at': self.consumed_at.isoformat() if self.consumed_at else None,
            'is_expired': self.is_expired,
            'is_consumed': self.is_consumed,
            'is_valid': self.is_valid,
            'consumption_attempts': self.consumption_attempts,
            'remaining_seconds': self.remaining_seconds,
            'device_fingerprint_match': (
                self.device_fingerprint == self.consumed_device_fingerprint
                if self.device_fingerprint and self.consumed_device_fingerprint
                else None
            )
        }
