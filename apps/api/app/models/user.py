"""
User model for authentication and profile management.
"""

from datetime import datetime
from typing import Optional, List

from sqlalchemy import (
    Boolean, String, Text, Index, CheckConstraint,
    DateTime, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import UserRole, Locale


class User(Base, TimestampMixin):
    """User account model."""
    
    __tablename__ = "users"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
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
    password_hash: Mapped[Optional[str]] = mapped_column(String(255))
    
    # Role and permissions
    role: Mapped[UserRole] = mapped_column(
        SQLEnum(UserRole), 
        nullable=False, 
        default=UserRole.ENGINEER,
        index=True
    )
    
    # Account status (Task 2.3 requirement for status field)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        index=True
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
    models: Mapped[List["Model"]] = relationship(
        "Model",
        back_populates="user"
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
    
    # Indexes
    __table_args__ = (
        Index('idx_users_phone', 'phone', postgresql_where='phone IS NOT NULL'),
        Index('idx_users_tax_no', 'tax_no', postgresql_where='tax_no IS NOT NULL'),
        Index('idx_users_created_at', 'created_at'),
        Index('idx_users_metadata', 'metadata', postgresql_using='gin', 
              postgresql_where='metadata IS NOT NULL'),
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