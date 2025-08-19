"""
License audit model for Task 4.1: Ultra-enterprise audit trail with hash-chain integrity.
Banking-grade implementation with Turkish KVKV compliance.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional
import hashlib
import json

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .license import License
    from .user import User


class LicenseAudit(Base):
    """License audit trail for state transitions and modifications.

    Task 4.1 Audit Requirements:
    - Immutable audit log for all license operations
    - Hash-chain integrity for tamper detection
    - Turkish KVKV compliance for data handling
    - Complete state transition tracking
    - User and system actor tracking
    """

    __tablename__ = "license_audit"

    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="Unique audit record identifier"
    )

    # Foreign keys
    license_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("licenses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="License being audited",
    )

    user_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="User who performed the action (null for system actions)",
    )

    # Audit event details
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Event type: license_assigned, license_extended, license_canceled, license_expired",
    )

    # State before and after
    old_state: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, comment="License state before the event"
    )

    new_state: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="License state after the event"
    )

    # Change details
    delta: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Specific changes made (e.g., extension duration, cancellation reason)",
    )

    # Actor information
    actor_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default=text("'user'"),
        comment="Actor type: user, system, admin, api",
    )

    actor_id: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Actor identifier (user_id, system_process, api_key, etc.)",
    )

    # Request context (KVKV compliant - no PII)
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45), nullable=True, comment="IP address of the request (anonymized for KVKV)"
    )

    user_agent: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, comment="User agent string"
    )

    # Hash-chain integrity
    previous_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, comment="SHA-256 hash of the previous audit record"
    )

    current_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, comment="SHA-256 hash of this audit record"
    )

    # Additional audit metadata (renamed from 'metadata' which is reserved in SQLAlchemy)
    audit_metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, server_default=text("'{}'"), comment="Additional audit metadata"
    )

    # Reason for the action (especially for cancellations)
    reason: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Human-readable reason for the action"
    )

    # Timestamp (immutable)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        index=True,
        comment="When the audit event occurred",
    )

    # Relationships
    license: Mapped["License"] = relationship("License", back_populates="audit_logs", lazy="select")

    user: Mapped[Optional["User"]] = relationship("User", foreign_keys=[user_id], lazy="select")

    # Enterprise indexes for audit queries
    __table_args__ = (
        # Performance indexes
        Index("idx_license_audit_license_event", "license_id", "event_type"),
        Index("idx_license_audit_created_at", "created_at"),
        Index("idx_license_audit_user_id", "user_id"),
        Index("idx_license_audit_event_type", "event_type"),
        # Hash-chain integrity index
        Index("idx_license_audit_previous_hash", "previous_hash"),
        # Composite index for audit trail queries
        Index(
            "idx_license_audit_license_created",
            "license_id",
            "created_at",
            postgresql_using="btree",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<LicenseAudit(id={self.id}, license_id={self.license_id}, event={self.event_type})>"
        )

    def __str__(self) -> str:
        return f"Audit {self.id}: {self.event_type} for License {self.license_id}"

    def to_dict(self) -> dict:
        """Convert audit record to dictionary for hashing."""
        return {
            "id": self.id,
            "license_id": self.license_id,
            "user_id": self.user_id,
            "event_type": self.event_type,
            "old_state": self.old_state,
            "new_state": self.new_state,
            "delta": self.delta,
            "actor_type": self.actor_type,
            "actor_id": self.actor_id,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "previous_hash": self.previous_hash,
        }

    @staticmethod
    def compute_hash(data: dict) -> str:
        """Compute SHA-256 hash of audit data for integrity."""
        # Create stable JSON representation
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def verify_hash_chain(self, previous_record: Optional["LicenseAudit"]) -> bool:
        """Verify the hash chain integrity."""
        if previous_record:
            return self.previous_hash == previous_record.current_hash
        else:
            # First record in chain
            return self.previous_hash is None
