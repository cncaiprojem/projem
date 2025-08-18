"""
MFA Backup Codes model for Task 3.7 ultra-enterprise TOTP authentication.

This model stores single-use backup codes for MFA recovery with:
- SHA-256 hashed codes for security
- Usage tracking with timestamps
- Automatic expiration
- Turkish KVKV compliance for personal data protection
"""

from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy import (
    String, Boolean, DateTime, ForeignKey, Index, CheckConstraint, Text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class MFABackupCode(Base, TimestampMixin):
    """MFA backup codes for recovery access with ultra-enterprise security."""
    
    __tablename__ = "mfa_backup_codes"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # User relationship
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    # Backup code data
    code_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment='SHA-256 hash of backup code'
    )
    code_hint: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        comment='First 4 and last 4 characters of code for identification'
    )
    
    # Usage tracking
    is_used: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment='Whether this backup code has been used'
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='When this code was used (if used)'
    )
    used_from_ip: Mapped[Optional[str]] = mapped_column(
        String(45),
        comment='IP address where code was used (IPv4/IPv6)'
    )
    used_user_agent: Mapped[Optional[str]] = mapped_column(
        Text,
        comment='User agent when code was used'
    )
    
    # Expiration and security
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment='Backup code expiration timestamp (90 days from creation)'
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="mfa_backup_codes"
    )
    
    # Indexes and constraints
    __table_args__ = (
        Index('idx_mfa_backup_codes_user_id', 'user_id'),
        Index('idx_mfa_backup_codes_code_hash', 'code_hash'),
        Index('idx_mfa_backup_codes_is_used', 'is_used'),
        Index('idx_mfa_backup_codes_expires_at', 'expires_at'),
        Index('idx_mfa_backup_codes_used_at', 'used_at',
              postgresql_where='used_at IS NOT NULL'),
        Index('idx_mfa_backup_codes_active', 'user_id', 'is_used', 'expires_at',
              postgresql_where='is_used = false AND expires_at > NOW()'),
        CheckConstraint(
            'expires_at > created_at',
            name='ck_mfa_backup_codes_expires_after_creation'
        ),
        CheckConstraint(
            '(is_used = false AND used_at IS NULL) OR (is_used = true AND used_at IS NOT NULL)',
            name='ck_mfa_backup_codes_usage_consistency'
        ),
    )
    
    def __repr__(self) -> str:
        return f"<MFABackupCode(id={self.id}, user_id={self.user_id}, used={self.is_used})>"
    
    def is_expired(self) -> bool:
        """Check if the backup code has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if the backup code is valid for use."""
        return not self.is_used and not self.is_expired()
    
    def mark_as_used(self, ip_address: Optional[str] = None, 
                     user_agent: Optional[str] = None) -> None:
        """Mark the backup code as used with audit information."""
        self.is_used = True
        self.used_at = datetime.now(timezone.utc)
        self.used_from_ip = ip_address
        self.used_user_agent = user_agent
    
    @classmethod
    def create_expiration_time(cls) -> datetime:
        """Create expiration time for new backup codes (90 days from now)."""
        return datetime.now(timezone.utc) + timedelta(days=90)
    
    def time_until_expiry(self) -> timedelta:
        """Get time remaining until expiration."""
        return self.expires_at - datetime.now(timezone.utc)
    
    def get_masked_hint(self) -> str:
        """Get masked representation for display."""
        if len(self.code_hint) == 8:
            return f"{self.code_hint[:4]}-****-{self.code_hint[4:]}"
        return f"{self.code_hint[:4]}-****"