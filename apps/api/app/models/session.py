"""
Session model for JWT refresh token management.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, ForeignKey, Index, DateTime
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Session(Base):
    """User authentication session with refresh token management."""
    
    __tablename__ = "sessions"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Foreign keys
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    
    # Token management
    refresh_token_hash: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )
    access_token_jti: Mapped[Optional[str]] = mapped_column(
        String(255),
        index=True
    )
    
    # Client information  
    device_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(1024),
        index=True
    )
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500))
    
    # Session lifecycle
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        index=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="NOW()"
    )
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="sessions")
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="session"
    )
    
    # Indexes
    __table_args__ = (
        Index('idx_sessions_user_id', 'user_id'),
        Index('idx_sessions_expires_at', 'expires_at',
              postgresql_where='revoked_at IS NULL'),
        Index('idx_sessions_device_fingerprint', 'device_fingerprint',
              postgresql_where='device_fingerprint IS NOT NULL'),
    )
    
    def __repr__(self) -> str:
        return f"<Session(id={self.id}, user_id={self.user_id}, expires_at={self.expires_at})>"
    
    @property
    def is_expired(self) -> bool:
        """Check if session has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @property
    def is_active(self) -> bool:
        """Check if session is active (not revoked or expired)."""
        return self.revoked_at is None and not self.is_expired