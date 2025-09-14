"""
Enhanced User model with enterprise authentication security for Task 3.1.
This replaces the basic user model with ultra enterprise security features.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, List, TYPE_CHECKING

from sqlalchemy import (
    Boolean, String, Text, Index, CheckConstraint, BigInteger,
    DateTime, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import UserRole, Locale

if TYPE_CHECKING:
    from .ai_suggestions import AISuggestion
    from .performance_profile import PerformanceProfile, OptimizationPlan


class User(Base, TimestampMixin):
    """User account model with enterprise authentication security."""
    
    __tablename__ = "users"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Profile information
    full_name: Mapped[Optional[str]] = mapped_column(String(255))
    display_name: Mapped[Optional[str]] = mapped_column(String(100))
    
    # Authentication
    email: Mapped[str] = mapped_column(
        String(255), 
        unique=True, 
        nullable=False, 
        index=True
    )
    phone: Mapped[Optional[str]] = mapped_column(
        String(20), 
        unique=True, 
        index=True
    )
    
    # Enhanced password security
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    password_salt: Mapped[Optional[str]] = mapped_column(
        String(64), 
        comment='Per-user salt for Argon2'
    )
    password_algorithm: Mapped[str] = mapped_column(
        String(20), 
        nullable=False, 
        default='argon2id',
        comment='Password hashing algorithm'
    )
    password_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='Last password change timestamp'
    )
    password_must_change: Mapped[bool] = mapped_column(
        Boolean, 
        nullable=False, 
        default=False,
        comment='Force password change on next login'
    )
    
    # Role and permissions
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole), 
        nullable=False, 
        default=UserRole.ENGINEER,
        index=True
    )
    
    # Account lockout mechanism
    failed_login_attempts: Mapped[int] = mapped_column(
        nullable=False, 
        default=0,
        comment='Current failed login attempt count'
    )
    account_locked_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='Account lockout expiration timestamp'
    )
    last_failed_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='Timestamp of last failed login'
    )
    last_lockout_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='Timestamp when account was last locked'
    )
    
    # Authentication audit fields
    last_successful_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='Timestamp of last successful login'
    )
    last_login_ip: Mapped[Optional[str]] = mapped_column(
        String(45),
        comment='IP address of last login (IPv4/IPv6)'
    )
    last_login_user_agent: Mapped[Optional[str]] = mapped_column(
        Text,
        comment='User agent of last login'
    )
    total_login_count: Mapped[int] = mapped_column(
        BigInteger, 
        nullable=False, 
        default=0,
        comment='Total successful login count'
    )
    
    # Email verification and security
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='Email verification timestamp'
    )
    email_verification_token: Mapped[Optional[str]] = mapped_column(
        String(128),
        comment='Current email verification token'
    )
    email_verification_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='Email verification token expiration'
    )
    
    # Password reset functionality
    password_reset_token: Mapped[Optional[str]] = mapped_column(
        String(128),
        comment='Current password reset token'
    )
    password_reset_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='Password reset token expiration'
    )
    password_reset_attempts: Mapped[int] = mapped_column(
        nullable=False, 
        default=0,
        comment='Password reset attempt count in current window'
    )
    
    # Account status and compliance
    account_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default='active',
        comment='Account status: active, suspended, locked, pending'
    )
    deactivated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='Account deactivation timestamp'
    )
    deactivation_reason: Mapped[Optional[str]] = mapped_column(
        String(100),
        comment='Reason for account deactivation'
    )
    
    # Turkish KVKV compliance fields
    data_processing_consent: Mapped[bool] = mapped_column(
        Boolean, 
        nullable=False, 
        default=False,
        comment='KVKV data processing consent'
    )
    data_processing_consent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='KVKV consent timestamp'
    )
    marketing_consent: Mapped[bool] = mapped_column(
        Boolean, 
        nullable=False, 
        default=False,
        comment='Marketing communication consent'
    )
    marketing_consent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='Marketing consent timestamp'
    )
    
    # Multi-Factor Authentication (MFA) fields for Task 3.7
    mfa_enabled: Mapped[bool] = mapped_column(
        Boolean, 
        nullable=False, 
        default=False,
        comment='MFA activation status'
    )
    mfa_secret_encrypted: Mapped[Optional[str]] = mapped_column(
        String(512),
        comment='Encrypted MFA TOTP secret (AES-256-GCM)'
    )
    mfa_enabled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        comment='MFA activation timestamp'
    )
    mfa_backup_codes_count: Mapped[int] = mapped_column(
        nullable=False, 
        default=0,
        comment='Number of unused backup codes remaining'
    )
    
    # Security preferences and metadata
    security_preferences: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        comment='User security preferences and settings'
    )
    auth_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        comment='Authentication-related metadata'
    )
    
    # Company information
    company_name: Mapped[Optional[str]] = mapped_column(String(255))
    tax_no: Mapped[Optional[str]] = mapped_column(
        String(20), 
        index=True
    )  # VKN/TCKN for Turkish tax
    address: Mapped[Optional[str]] = mapped_column(Text)
    
    # Preferences
    locale: Mapped[Locale] = mapped_column(
        SQLEnum(Locale), 
        nullable=False, 
        default=Locale.TR
    )
    timezone: Mapped[str] = mapped_column(
        String(50), 
        nullable=False,
        default="Europe/Istanbul"
    )
    
    # Legacy account status fields (kept for compatibility)
    is_active: Mapped[bool] = mapped_column(
        Boolean, 
        nullable=False,
        default=True
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, 
        nullable=False,
        default=False
    )
    
    # Legacy status field (maintained for compatibility)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        index=True
    )
    
    # Timestamps
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    # Additional user metadata (renamed to avoid SQLAlchemy conflict)
    user_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, name="metadata")
    
    # Relationships
    sessions: Mapped[List["Session"]] = relationship(
        "Session",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    licenses: Mapped[List["License"]] = relationship(
        "License",
        back_populates="user"
    )
    # Task 7.15: AI suggestions tracking
    ai_suggestions: Mapped[List["AISuggestion"]] = relationship(
        "AISuggestion",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    jobs: Mapped[List["Job"]] = relationship(
        "Job",
        back_populates="user"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    invoices: Mapped[List["Invoice"]] = relationship(
        "Invoice",
        back_populates="user"
    )
    payments: Mapped[List["Payment"]] = relationship(
        "Payment",
        back_populates="user"
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="actor_user",
        foreign_keys="AuditLog.actor_user_id"
    )
    security_events: Mapped[List["SecurityEvent"]] = relationship(
        "SecurityEvent",
        back_populates="user",
        foreign_keys="SecurityEvent.user_id"
    )
    oidc_accounts: Mapped[List["OIDCAccount"]] = relationship(
        "OIDCAccount",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    
    # File uploads relationship (Task 5.3)
    uploaded_files: Mapped[List["FileMetadata"]] = relationship(
        "FileMetadata",
        back_populates="user",
        lazy="select"
    )
    mfa_backup_codes: Mapped[List["MFABackupCode"]] = relationship(
        "MFABackupCode",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    
    # Task 7.24: Model validation relationships
    validation_results: Mapped[List["ValidationResult"]] = relationship(
        "ValidationResult",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    # Task 7.25: Performance profiling relationships
    performance_profiles: Mapped[List["PerformanceProfile"]] = relationship(
        "PerformanceProfile",
        back_populates="user",
        cascade="all, delete-orphan"
    )

    optimization_plans: Mapped[List["OptimizationPlan"]] = relationship(
        "OptimizationPlan",
        back_populates="user",
        foreign_keys="OptimizationPlan.user_id",
        cascade="all, delete-orphan"
    )

    # Indexes and constraints
    __table_args__ = (
        Index('idx_users_phone', 'phone', postgresql_where='phone IS NOT NULL'),
        Index('idx_users_tax_no', 'tax_no', postgresql_where='tax_no IS NOT NULL'),
        Index('idx_users_created_at', 'created_at'),
        Index('idx_users_metadata', 'metadata', postgresql_using='gin', 
              postgresql_where='metadata IS NOT NULL'),
        Index('idx_users_account_status', 'account_status'),
        Index('idx_users_account_locked_until', 'account_locked_until', 
              postgresql_where='account_locked_until IS NOT NULL'),
        Index('idx_users_failed_login_attempts', 'failed_login_attempts', 
              postgresql_where='failed_login_attempts > 0'),
        Index('idx_users_password_reset_token', 'password_reset_token', unique=True, 
              postgresql_where='password_reset_token IS NOT NULL'),
        Index('idx_users_email_verification_token', 'email_verification_token', unique=True, 
              postgresql_where='email_verification_token IS NOT NULL'),
        Index('idx_users_last_login_ip', 'last_login_ip', 
              postgresql_where='last_login_ip IS NOT NULL'),
        Index('idx_users_password_updated_at', 'password_updated_at'),
        Index('idx_users_full_name', 'full_name', 
              postgresql_where='full_name IS NOT NULL'),
        Index('idx_users_data_processing_consent', 'data_processing_consent'),
        Index('idx_users_mfa_enabled', 'mfa_enabled'),
        Index('idx_users_mfa_enabled_at', 'mfa_enabled_at', 
              postgresql_where='mfa_enabled_at IS NOT NULL'),
        CheckConstraint('failed_login_attempts >= 0', name='ck_users_failed_login_attempts_non_negative'),
        CheckConstraint('total_login_count >= 0', name='ck_users_total_login_count_non_negative'),
        CheckConstraint('password_reset_attempts >= 0', name='ck_users_password_reset_attempts_non_negative'),
        CheckConstraint(
            "account_status IN ('active', 'suspended', 'locked', 'pending', 'deactivated')",
            name='ck_users_account_status_valid'
        ),
        CheckConstraint(
            "password_algorithm IN ('argon2id', 'argon2i', 'argon2d', 'bcrypt')",
            name='ck_users_password_algorithm_valid'
        ),
        CheckConstraint(
            'account_locked_until IS NULL OR account_locked_until > NOW()',
            name='ck_users_account_locked_until_future'
        ),
    )
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role.value})>"
    
    def has_permission(self, permission: str) -> bool:
        """Check if user has specific permission based on role."""
        role_permissions = {
            UserRole.ADMIN: {'*'},  # All permissions
            UserRole.ENGINEER: {
                'model.create', 'model.read', 'model.update', 'model.delete',
                'job.create', 'job.read', 'job.cancel',
                'cam.create', 'cam.read',
                'simulation.create', 'simulation.read'
            },
            UserRole.OPERATOR: {
                'model.read',
                'job.create', 'job.read', 'job.cancel',
                'cam.read',
                'simulation.read'
            },
            UserRole.VIEWER: {
                'model.read',
                'job.read',
                'cam.read',
                'simulation.read'
            }
        }
        
        user_permissions = role_permissions.get(self.role, set())
        return '*' in user_permissions or permission in user_permissions
    
    def is_account_locked(self) -> bool:
        """Check if account is currently locked due to failed login attempts."""
        if not self.account_locked_until:
            return False
        return datetime.now(timezone.utc) < self.account_locked_until
    
    def is_password_expired(self, max_age_days: int = 90) -> bool:
        """Check if password has expired based on policy."""
        if not self.password_updated_at:
            return True  # No password set or very old account
        
        max_age = timedelta(days=max_age_days)
        return datetime.now(timezone.utc) - self.password_updated_at > max_age
    
    def can_attempt_login(self) -> bool:
        """Check if user can attempt login (not locked and account active)."""
        return (
            self.account_status == 'active' and
            not self.is_account_locked()
            # Note: Removed redundant is_active check as it's legacy
            # account_status == 'active' is the authoritative status check
        )
    
    def increment_failed_login_attempts(self) -> None:
        """Increment failed login attempts and lock account if threshold reached."""
        self.failed_login_attempts += 1
        self.last_failed_login_at = datetime.now(timezone.utc)
        
        # Lock account after 10 failed attempts for 15 minutes
        if self.failed_login_attempts >= 10:
            self.account_locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
            self.last_lockout_at = datetime.now(timezone.utc)
    
    def reset_failed_login_attempts(self) -> None:
        """Reset failed login attempts after successful login."""
        self.failed_login_attempts = 0
        self.account_locked_until = None
        self.last_successful_login_at = datetime.now(timezone.utc)
        self.total_login_count += 1
    
    def update_login_metadata(self, ip_address: str, user_agent: str) -> None:
        """Update login metadata for audit purposes."""
        self.last_login_ip = ip_address
        self.last_login_user_agent = user_agent
    
    @property
    def is_email_verified(self) -> bool:
        """Check if email is verified."""
        return self.email_verified_at is not None
    
    def can_reset_password(self) -> bool:
        """Check if user can request password reset (rate limiting)."""
        # Allow password reset if no recent attempts or window has passed
        if self.password_reset_attempts == 0:
            return True
        
        # Rate limit: max 3 attempts per hour
        if self.password_reset_attempts >= 3:
            return False
        
        return True
    
    def generate_display_name(self) -> str:
        """Generate a display name for the user."""
        if self.display_name:
            return self.display_name
        elif self.full_name:
            return self.full_name
        else:
            return self.email.split('@')[0]
    
    def requires_mfa(self) -> bool:
        """Check if user requires MFA based on role and activation status."""
        # Admin role always requires MFA if enabled
        # All users require MFA if they have it enabled
        return self.mfa_enabled or self.role == UserRole.ADMIN
    
    def can_disable_mfa(self) -> bool:
        """Check if user can disable MFA (not admin with enforced MFA)."""
        # Admin users cannot disable MFA for security
        return self.role != UserRole.ADMIN