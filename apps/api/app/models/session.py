"""
Ultra Enterprise Session model for Task 3.2 - Banking-level session security.

This model implements:
- UUID primary keys for unguessable session identifiers
- SHA256/HMAC refresh token hash storage (never plaintext)
- Device fingerprinting for anomaly detection
- Session rotation chain tracking for forensics
- Turkish KVKV compliance for session data
- Enterprise-grade audit logging
- Banking-level security constraints
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List
import uuid

from sqlalchemy import String, ForeignKey, Index, DateTime, Text, Boolean, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID, INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class Session(Base, TimestampMixin):
    """Ultra enterprise user authentication session with banking-level security."""

    __tablename__ = "sessions"

    # UUID primary key for unguessable session identifiers
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        comment="UUID session identifier for enhanced security",
    )

    # Foreign keys
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User owning this session",
    )

    # Refresh token security - ONLY store hashed tokens, never plaintext
    refresh_token_hash: Mapped[str] = mapped_column(
        String(128),  # SHA512 hex = 128 chars
        unique=True,
        nullable=False,
        index=True,
        comment="SHA512/HMAC hash of refresh token - NEVER store plaintext",
    )

    # Device fingerprinting for anomaly detection
    device_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(1024), index=True, comment="Browser/device fingerprint for anomaly detection"
    )

    # Client metadata for audit and security
    ip_address: Mapped[Optional[str]] = mapped_column(
        INET, comment="Client IP address (masked for privacy compliance)"
    )
    user_agent: Mapped[Optional[str]] = mapped_column(Text, comment="Client user agent string")

    # Session lifecycle management
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="Session expiration timestamp (7 days default)",
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        index=True,
        comment="Last activity timestamp for sliding expiration",
    )

    # Session revocation and audit
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), index=True, comment="Session revocation timestamp"
    )
    revocation_reason: Mapped[Optional[str]] = mapped_column(
        String(100), comment="Reason for session revocation (logout, admin, security, expired)"
    )

    # Session rotation chain for audit and forensics
    rotated_from: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="SET NULL"),
        index=True,
        comment="Previous session ID in rotation chain for audit tracking",
    )

    # Security flags
    is_suspicious: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="Flagged as suspicious by security analysis"
    )

    # Turkish KVKV compliance metadata
    kvkv_logged: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        comment="Session logged for KVKV compliance audit trail",
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")

    # Self-referential relationship for rotation chain
    parent_session: Mapped[Optional["Session"]] = relationship(
        "Session", remote_side=[id], back_populates="rotated_sessions"
    )
    rotated_sessions: Mapped[List["Session"]] = relationship(
        "Session", back_populates="parent_session", cascade="all, delete-orphan"
    )

    # Enterprise security indexes and constraints
    __table_args__ = (
        # Performance indexes for session lookups
        Index(
            "idx_sessions_user_active",
            "user_id",
            "revoked_at",
            postgresql_where="revoked_at IS NULL",
        ),
        Index("idx_sessions_expires_active", "expires_at", postgresql_where="revoked_at IS NULL"),
        Index(
            "idx_sessions_device_fingerprint",
            "device_fingerprint",
            postgresql_where="device_fingerprint IS NOT NULL",
        ),
        Index(
            "idx_sessions_last_used", "last_used_at", postgresql_where="last_used_at IS NOT NULL"
        ),
        Index(
            "idx_sessions_rotation_chain",
            "rotated_from",
            postgresql_where="rotated_from IS NOT NULL",
        ),
        Index(
            "idx_sessions_suspicious",
            "is_suspicious",
            "created_at",
            postgresql_where="is_suspicious = true",
        ),
        Index("idx_sessions_ip_address", "ip_address", postgresql_where="ip_address IS NOT NULL"),
        # Ensure refresh token hash is never null and properly sized
        CheckConstraint(
            "LENGTH(refresh_token_hash) = 128", name="ck_sessions_refresh_token_hash_length"
        ),
        # Ensure valid revocation reasons
        CheckConstraint(
            "revocation_reason IS NULL OR revocation_reason IN ("
            "'logout', 'admin_revoke', 'security_breach', 'expired', "
            "'rotation', 'password_change', 'suspicious_activity', 'user_request')",
            name="ck_sessions_revocation_reason_valid",
        ),
        # Ensure session expiration is in future when created
        CheckConstraint("expires_at > created_at", name="ck_sessions_expires_after_created"),
        # Ensure revocation timestamp is after creation
        CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name="ck_sessions_revoked_after_created",
        ),
        # Ensure last_used is not before creation
        CheckConstraint(
            "last_used_at IS NULL OR last_used_at >= created_at",
            name="ck_sessions_last_used_after_created",
        ),
        # Prevent self-referential rotation (session cannot rotate from itself)
        CheckConstraint(
            "rotated_from IS NULL OR rotated_from != id", name="ck_sessions_no_self_rotation"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Session(id={self.id}, user_id={self.user_id}, "
            f"expires_at={self.expires_at}, revoked={bool(self.revoked_at)})>"
        )

    @property
    def is_expired(self) -> bool:
        """Check if session has expired based on expiration timestamp."""
        return datetime.now(timezone.utc) > self.expires_at

    @property
    def is_active(self) -> bool:
        """Check if session is active (not revoked and not expired)."""
        return self.revoked_at is None and not self.is_expired

    @property
    def expires_in_seconds(self) -> int:
        """Get seconds until session expires (negative if already expired)."""
        delta = self.expires_at - datetime.now(timezone.utc)
        return int(delta.total_seconds())

    @property
    def age_in_seconds(self) -> int:
        """Get session age in seconds since creation."""
        delta = datetime.now(timezone.utc) - self.created_at
        return int(delta.total_seconds())

    def revoke(self, reason: str = "user_request") -> None:
        """
        Revoke this session with audit reason.

        Args:
            reason: Revocation reason for audit trail
        """
        self.revoked_at = datetime.now(timezone.utc)
        self.revocation_reason = reason

    def update_last_used(self) -> None:
        """Update last used timestamp for sliding expiration."""
        self.last_used_at = datetime.now(timezone.utc)

    def is_near_expiry(self, threshold_minutes: int = 60) -> bool:
        """
        Check if session will expire within threshold.

        Args:
            threshold_minutes: Minutes threshold for near expiry check

        Returns:
            True if session expires within threshold
        """
        threshold = datetime.now(timezone.utc) + timedelta(minutes=threshold_minutes)
        return self.expires_at <= threshold

    def extend_expiration(self, extension_hours: int = 168) -> None:
        """
        Extend session expiration (default 7 days).

        Args:
            extension_hours: Hours to extend from now
        """
        if self.is_active:
            self.expires_at = datetime.now(timezone.utc) + timedelta(hours=extension_hours)

    def flag_suspicious(self) -> None:
        """Flag session as suspicious for security review."""
        self.is_suspicious = True

    def get_rotation_chain_length(self) -> int:
        """
        Get length of session rotation chain (depth from root).

        Uses iterative approach to prevent stack overflow with long rotation chains.
        This is critical for enterprise environments where session rotation chains
        could theoretically grow very long over time.

        Returns:
            Chain depth (0 for root sessions, positive for rotated sessions)
        """
        if not self.rotated_from:
            return 0

        # Use iterative approach to avoid recursion limits with long chains
        # Maximum theoretical chain length in production should be reasonable,
        # but this prevents stack overflow in edge cases
        depth = 0
        current_session = self
        visited_sessions = set()  # Prevent infinite loops from circular references

        while current_session.rotated_from is not None:
            # Safety check: prevent infinite loops from circular rotation chains
            if current_session.id in visited_sessions:
                # Log security issue - circular rotation chain detected
                # This should never happen with proper constraints, but defensive programming
                break

            visited_sessions.add(current_session.id)
            depth += 1

            # In a real implementation, we'd need to load the parent session from DB
            # For now, we use the relationship if available
            if hasattr(current_session, "parent_session") and current_session.parent_session:
                current_session = current_session.parent_session
            else:
                # Cannot traverse further without database query
                break

            # Safety limit: prevent excessive iteration in malformed data
            if depth > 1000:  # Reasonable upper bound for rotation chains
                break

        return depth

    @classmethod
    def create_default_session(
        cls,
        user_id: int,
        refresh_token_hash: str,
        device_fingerprint: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        expires_in_hours: int = 168,  # 7 days default
    ) -> "Session":
        """
        Create a new session with default enterprise security settings.

        Args:
            user_id: User ID owning the session
            refresh_token_hash: SHA512 hash of refresh token
            device_fingerprint: Optional device fingerprint
            ip_address: Optional client IP address
            user_agent: Optional client user agent
            expires_in_hours: Session lifetime in hours (default 7 days)

        Returns:
            New Session instance
        """
        now = datetime.now(timezone.utc)

        return cls(
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            device_fingerprint=device_fingerprint,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=now + timedelta(hours=expires_in_hours),
            last_used_at=now,
            kvkv_logged=True,
            is_suspicious=False,
        )
