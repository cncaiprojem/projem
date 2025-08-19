"""
Idempotency key model for API request deduplication.
Task 4.11: Ensures exactly-once API semantics for critical financial operations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .user import User


class IdempotencyKey(Base, TimestampMixin):
    """Store idempotency keys to prevent duplicate API operations.
    
    ENTERPRISE DESIGN PRINCIPLES:
    - Unique constraint on (user_id, key) for user-scoped idempotency
    - TTL-based expiration for automatic cleanup
    - Response caching for identical retries
    - Request hash validation for consistency
    """

    __tablename__ = "idempotency_keys"

    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # User scope (idempotency is per-user)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="User who made the request"
    )

    # Idempotency key from header
    key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Idempotency-Key header value"
    )

    # Request fingerprint
    request_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="API endpoint path"
    )

    request_method: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="HTTP method"
    )

    request_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA256 hash of request body"
    )

    # Cached response
    response_status: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="HTTP response status code"
    )

    response_body: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Cached response body"
    )

    # Expiration
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
        comment="When this idempotency key expires"
    )

    # Processing state
    is_processing: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether request is currently being processed"
    )

    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When processing started (for timeout detection)"
    )

    # Relationships
    user: Mapped[User] = relationship(
        "User",
        back_populates="idempotency_keys",
        lazy="select"
    )

    __table_args__ = (
        # Unique constraint on user + key
        UniqueConstraint(
            "user_id", "key",
            name="uq_idempotency_keys_user_key"
        ),

        # Index for cleanup queries
        Index(
            "idx_idempotency_keys_expires_at",
            "expires_at"
        ),

        # Index for finding processing timeouts
        Index(
            "idx_idempotency_keys_processing",
            "is_processing", "processing_started_at",
            postgresql_where="is_processing = true"
        ),
    )

    def __repr__(self) -> str:
        return f"<IdempotencyKey(id={self.id}, key='{self.key}', user_id={self.user_id})>"

    @classmethod
    def create_for_request(
        cls,
        user_id: int,
        key: str,
        request_path: str,
        request_method: str,
        request_hash: str,
        ttl_hours: int = 24
    ) -> IdempotencyKey:
        """Create a new idempotency key with expiration."""
        return cls(
            user_id=user_id,
            key=key,
            request_path=request_path,
            request_method=request_method,
            request_hash=request_hash,
            expires_at=datetime.now(UTC) + timedelta(hours=ttl_hours),
            is_processing=True,
            processing_started_at=datetime.now(UTC)
        )

    def is_expired(self) -> bool:
        """Check if this idempotency key has expired."""
        return datetime.now(UTC) > self.expires_at

    def is_timeout(self, timeout_seconds: int = 60) -> bool:
        """Check if processing has timed out."""
        if not self.is_processing or not self.processing_started_at:
            return False
        elapsed = datetime.now(UTC) - self.processing_started_at
        return elapsed.total_seconds() > timeout_seconds

    def complete_processing(
        self,
        response_status: int,
        response_body: dict | None = None
    ) -> None:
        """Mark processing as complete with response."""
        self.is_processing = False
        self.response_status = response_status
        self.response_body = response_body
