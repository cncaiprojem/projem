"""
Security event model for ultra enterprise security monitoring.
Compliant with Task Master ERD requirements.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger, DateTime, ForeignKey, Index, String, Text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .user import User


class SecurityEvent(Base):
    """Enterprise security event tracking for compliance and monitoring.
    
    Records security-related events with minimal overhead for high-frequency
    logging while maintaining audit trail integrity.
    """
    
    __tablename__ = "security_events"
    __table_args__ = (
        # Performance indexes
        Index("idx_security_events_user_id", "user_id"),
        Index("idx_security_events_type", "type"),
        Index("idx_security_events_created_at", "created_at"),
        Index(
            "idx_security_events_user_type", 
            "user_id", "type", "created_at"
        ),
        Index(
            "idx_security_events_correlation_id", 
            "correlation_id",
            postgresql_where="correlation_id IS NOT NULL"
        ),
        Index(
            "idx_security_events_session_id", 
            "session_id",
            postgresql_where="session_id IS NOT NULL"
        ),
        Index(
            "idx_security_events_ip_masked_created", 
            "ip_masked", "created_at",
            postgresql_where="ip_masked IS NOT NULL"
        ),
    )
    
    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Unique security event identifier"
    )
    
    # User association
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Associated user (NULL for anonymous/system events)"
    )
    
    # Event classification
    type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Security event type (e.g., 'LOGIN_FAILED', 'ACCESS_DENIED')"
    )
    
    # Request context with correlation tracking
    session_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Session ID for user session tracking"
    )
    correlation_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Request correlation ID for tracing across services"
    )
    resource: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Resource being accessed or affected"
    )
    ip_masked: Mapped[Optional[str]] = mapped_column(
        String(45),  # IPv6 compatible
        nullable=True,
        index=True,
        comment="KVKV-compliant masked IP address (privacy-preserving)"
    )
    ua_masked: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="KVKV-compliant masked user agent string"
    )
    event_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional security event metadata"
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="NOW()",
        index=True,
        comment="When the security event occurred (UTC)"
    )
    
    # Relationships
    user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="security_events",
        foreign_keys=[user_id]
    )
    
    def __repr__(self) -> str:
        return (
            f"<SecurityEvent(id={self.id}, type='{self.type}', "
            f"user_id={self.user_id}, ip='{self.ip}')>"
        )
    
    @property
    def is_anonymous(self) -> bool:
        """Check if event is from anonymous/unauthenticated source."""
        return self.user_id is None
    
    @property
    def is_authenticated(self) -> bool:
        """Check if event is from authenticated user."""
        return self.user_id is not None
    
    @property
    def has_ip(self) -> bool:
        """Check if event has IP address information."""
        return self.ip is not None
    
    @property
    def has_user_agent(self) -> bool:
        """Check if event has user agent information."""
        return self.ua is not None and self.ua.strip() != ""
    
    @classmethod
    def create_login_failed(
        cls,
        user_id: Optional[int] = None,
        ip: Optional[str] = None,
        ua: Optional[str] = None
    ) -> "SecurityEvent":
        """Create a login failed security event.
        
        Args:
            user_id: User ID if known
            ip: Source IP address
            ua: User agent string
            
        Returns:
            SecurityEvent instance
        """
        return cls(
            user_id=user_id,
            type="LOGIN_FAILED",
            ip=ip,
            ua=ua
        )
    
    @classmethod
    def create_access_denied(
        cls,
        user_id: int,
        ip: Optional[str] = None,
        ua: Optional[str] = None
    ) -> "SecurityEvent":
        """Create an access denied security event.
        
        Args:
            user_id: User ID who was denied access
            ip: Source IP address
            ua: User agent string
            
        Returns:
            SecurityEvent instance
        """
        return cls(
            user_id=user_id,
            type="ACCESS_DENIED",
            ip=ip,
            ua=ua
        )
    
    @classmethod
    def create_suspicious_activity(
        cls,
        user_id: Optional[int],
        activity_type: str,
        ip: Optional[str] = None,
        ua: Optional[str] = None
    ) -> "SecurityEvent":
        """Create a suspicious activity security event.
        
        Args:
            user_id: User ID if known
            activity_type: Type of suspicious activity
            ip: Source IP address
            ua: User agent string
            
        Returns:
            SecurityEvent instance
        """
        return cls(
            user_id=user_id,
            type=f"SUSPICIOUS_{activity_type.upper()}",
            ip=ip,
            ua=ua
        )
    
    def is_login_related(self) -> bool:
        """Check if event is related to authentication/login."""
        login_types = [
            "LOGIN_FAILED",
            "LOGIN_SUCCESS", 
            "LOGIN_BLOCKED",
            "BRUTE_FORCE_DETECTED",
            "ACCOUNT_LOCKED"
        ]
        return self.type in login_types
    
    def is_access_related(self) -> bool:
        """Check if event is related to authorization/access."""
        access_types = [
            "ACCESS_DENIED",
            "PRIVILEGE_ESCALATION",
            "UNAUTHORIZED_ACCESS",
            "RESOURCE_ACCESS_DENIED"
        ]
        return self.type in access_types
    
    def is_suspicious(self) -> bool:
        """Check if event indicates suspicious activity."""
        return (
            self.type.startswith("SUSPICIOUS_") or
            self.type in [
                "BRUTE_FORCE_DETECTED",
                "RATE_LIMIT_EXCEEDED",
                "UNUSUAL_LOCATION",
                "MULTIPLE_DEVICES"
            ]
        )