"""
Audit log model with hash-chain integrity.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, ForeignKey, Index,
    DateTime, Enum as SQLEnum, Text, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import JSONB, INET
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .enums import AuditAction


class AuditLog(Base):
    """Comprehensive audit trail with hash-chain integrity."""
    
    __tablename__ = "audit_logs"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Foreign keys
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True
    )
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL")
    )
    
    # Audit action
    action: Mapped[AuditAction] = mapped_column(
        SQLEnum(AuditAction),
        nullable=False,
        index=True
    )
    
    # Entity information
    entity_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True
    )
    entity_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        index=True
    )
    
    # Data snapshots
    entity_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    changes: Mapped[Optional[dict]] = mapped_column(JSONB)
    
    # Request information
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    
    # Hash chain
    chain_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True
    )
    prev_chain_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="NOW()",
        index=True
    )
    
    # Relationships
    user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="audit_logs",
        foreign_keys=[user_id]
    )
    session: Mapped[Optional["Session"]] = relationship(
        "Session",
        back_populates="audit_logs"
    )
    
    # Constraints and indexes
    __table_args__ = (
        UniqueConstraint('chain_hash', name='uq_audit_logs_chain_hash'),
        Index('idx_audit_logs_user_id', 'user_id',
              postgresql_where='user_id IS NOT NULL'),
        Index('idx_audit_logs_entity', 'entity_type', 'entity_id'),
        Index('idx_audit_logs_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, action={self.action.value}, "
            f"entity={self.entity_type}:{self.entity_id})>"
        )
    
    @property
    def is_authenticated(self) -> bool:
        """Check if action was performed by authenticated user."""
        return self.user_id is not None
    
    @property
    def is_system_action(self) -> bool:
        """Check if action was performed by system."""
        return self.user_id is None
    
    def get_change(self, field: str):
        """Get specific field change."""
        if not self.changes or field not in self.changes:
            return None
        return self.changes[field]
    
    def has_changes(self) -> bool:
        """Check if audit entry has changes."""
        return bool(self.changes)
    
    def verify_chain(self, prev_entry: Optional["AuditLog"]) -> bool:
        """Verify hash chain continuity with previous entry."""
        if prev_entry is None:
            # First entry should have genesis hash
            return self.prev_chain_hash == "0" * 64
        return self.prev_chain_hash == prev_entry.chain_hash