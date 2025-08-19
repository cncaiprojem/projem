"""
OIDC Account Model for Task 3.5 - Google OAuth2/OIDC Integration

This model manages the linking between local User accounts and external OIDC providers
(primarily Google) with ultra enterprise security standards.
"""

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import String, Boolean, ForeignKey, Index, DateTime
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class OIDCAccount(Base, TimestampMixin):
    """OIDC account linking model with enterprise security."""

    __tablename__ = "oidc_accounts"

    # Primary key (UUID for enhanced security)
    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
        comment="OIDC account UUID",
    )

    # Foreign key to User table
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Reference to local user account",
    )

    # OIDC provider information
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="OIDC provider name (e.g., 'google')"
    )

    # OIDC subject identifier (unique per provider)
    sub: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="OIDC subject identifier from provider"
    )

    # User profile information from OIDC provider
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="Email address from OIDC provider"
    )

    email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, comment="Whether email is verified by OIDC provider"
    )

    picture: Mapped[Optional[str]] = mapped_column(
        String(500), comment="Profile picture URL from OIDC provider"
    )

    # Provider-specific metadata
    provider_data: Mapped[Optional[dict]] = mapped_column(
        JSONB, comment="Additional provider-specific data (JSON)"
    )

    # Security tracking
    first_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), comment="First login timestamp for this OIDC account"
    )

    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), comment="Last login timestamp for this OIDC account"
    )

    login_count: Mapped[int] = mapped_column(
        default=0, comment="Total number of logins via this OIDC account"
    )

    # Account status
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="Whether this OIDC account is active"
    )

    # Relationship to User
    user: Mapped["User"] = relationship("User", back_populates="oidc_accounts", lazy="joined")

    # Database constraints and indexes
    __table_args__ = (
        # Unique constraint: One OIDC account per provider per subject
        Index("ix_oidc_accounts_provider_sub", "provider", "sub", unique=True),
        # Index for efficient lookups
        Index("ix_oidc_accounts_user_id", "user_id"),
        Index("ix_oidc_accounts_email", "email"),
        Index("ix_oidc_accounts_provider", "provider"),
        Index("ix_oidc_accounts_is_active", "is_active"),
        # Performance index for audit queries
        Index("ix_oidc_accounts_last_login", "last_login_at"),
    )

    def __repr__(self) -> str:
        return f"<OIDCAccount(id={self.id}, provider={self.provider}, user_id={self.user_id})>"

    def record_login(self) -> None:
        """Record a successful login via this OIDC account."""
        now = datetime.now(timezone.utc)

        if self.first_login_at is None:
            self.first_login_at = now

        self.last_login_at = now
        self.login_count += 1

    def is_email_match(self, email: str) -> bool:
        """Check if the provided email matches this OIDC account's email."""
        return self.email.lower() == email.lower()

    def get_masked_email(self) -> str:
        """Get email with masking for audit logs (PII protection)."""
        if not self.email or "@" not in self.email:
            return "***@***.***"

        username, domain = self.email.rsplit("@", 1)

        # Mask username (show first and last char if > 2 chars)
        if len(username) <= 2:
            masked_username = "*" * len(username)
        else:
            masked_username = username[0] + "*" * (len(username) - 2) + username[-1]

        # Mask domain (show domain extension)
        if "." in domain:
            domain_parts = domain.split(".")
            masked_domain = "*" * len(domain_parts[0]) + "." + ".".join(domain_parts[1:])
        else:
            masked_domain = "*" * len(domain)

        return f"{masked_username}@{masked_domain}"

    @classmethod
    def find_by_provider_sub(cls, session, provider: str, sub: str) -> Optional["OIDCAccount"]:
        """Find OIDC account by provider and subject identifier."""
        return (
            session.query(cls)
            .filter(cls.provider == provider, cls.sub == sub, cls.is_active == True)
            .first()
        )

    @classmethod
    def find_by_user_and_provider(
        cls, session, user_id: int, provider: str
    ) -> Optional["OIDCAccount"]:
        """Find OIDC account by user ID and provider."""
        return (
            session.query(cls)
            .filter(cls.user_id == user_id, cls.provider == provider, cls.is_active == True)
            .first()
        )
