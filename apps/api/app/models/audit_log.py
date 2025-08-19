"""
Audit log model with hash-chain integrity for ultra enterprise compliance.
Compliant with Task Master ERD requirements.
"""

import hashlib
import json
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base

if TYPE_CHECKING:
    from .user import User


class AuditLog(Base):
    """Enterprise audit trail with cryptographic hash-chain integrity.
    
    Provides immutable audit logging with hash-chain verification
    for regulatory compliance and data integrity assurance.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        # Hash format validation
        CheckConstraint(
            "char_length(chain_hash) = 64 AND chain_hash ~ '^[0-9a-f]{64}$'",
            name="ck_audit_logs_chain_hash_format"
        ),
        CheckConstraint(
            "char_length(prev_chain_hash) = 64 AND prev_chain_hash ~ '^[0-9a-f]{64}$'",
            name="ck_audit_logs_prev_chain_hash_format"
        ),
        # Performance indexes
        Index(
            "idx_audit_logs_scope_created",
            "scope_type", "scope_id", "created_at"
        ),
        Index("idx_audit_logs_event_type", "event_type"),
        Index(
            "idx_audit_logs_payload_gin",
            "payload",
            postgresql_using="gin",
            postgresql_where="payload IS NOT NULL"
        ),
        Index(
            "idx_audit_logs_actor_user",
            "actor_user_id",
            postgresql_where="actor_user_id IS NOT NULL"
        ),
        Index(
            "idx_audit_logs_correlation_id",
            "correlation_id",
            postgresql_where="correlation_id IS NOT NULL"
        ),
        Index(
            "idx_audit_logs_session_id",
            "session_id",
            postgresql_where="session_id IS NOT NULL"
        ),
    )

    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True,
        comment="Unique audit log entry identifier"
    )

    # Scope identification (what entity is being audited)
    scope_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Type of entity being audited (e.g., 'job', 'user', 'payment')"
    )
    scope_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        index=True,
        comment="ID of the specific entity being audited"
    )

    # Actor identification (who performed the action)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="User who performed the audited action (NULL for system actions)"
    )

    # Event details
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Type of action performed (e.g., 'CREATE', 'UPDATE', 'DELETE')"
    )

    # Correlation tracking for request tracing
    correlation_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Request correlation ID for tracing across services"
    )
    session_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Session ID for user session tracking"
    )
    resource: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Resource being audited"
    )
    ip_masked: Mapped[str | None] = mapped_column(
        String(45),  # IPv6 compatible
        nullable=True,
        comment="KVKV-compliant masked IP address"
    )
    ua_masked: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="KVKV-compliant masked user agent"
    )

    payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Structured data about the audited event"
    )

    # Hash-chain integrity
    prev_chain_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA256 hash of previous audit log entry (genesis: '0' * 64)"
    )
    chain_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        comment="SHA256 hash of this entry (prev_hash + canonical_json(payload))"
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="NOW()",
        index=True,
        comment="When the audit event occurred (UTC)"
    )

    # Relationships
    actor_user: Mapped[Optional["User"]] = relationship(
        "User",
        back_populates="audit_logs",
        foreign_keys=[actor_user_id]
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, event_type='{self.event_type}', "
            f"scope={self.scope_type}:{self.scope_id})>"
        )

    @classmethod
    def compute_chain_hash(cls, prev_hash: str, payload: dict[str, Any] | None) -> str:
        """Compute SHA256 hash for hash-chain integrity.
        
        Args:
            prev_hash: Previous entry's chain_hash (or genesis hash)
            payload: Event payload data
            
        Returns:
            64-character hex SHA256 hash
        """
        # Create canonical JSON representation
        if payload is None:
            canonical_payload = ""
        else:
            canonical_payload = json.dumps(
                payload,
                sort_keys=True,
                separators=(',', ':'),
                ensure_ascii=False
            )

        # Compute hash: SHA256(prev_hash || canonical_json)
        hash_input = prev_hash + canonical_payload
        return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()

    @classmethod
    def get_genesis_hash(cls) -> str:
        """Get the genesis hash for the first audit log entry."""
        return "0" * 64

    def verify_chain_integrity(self, prev_entry: Optional["AuditLog"]) -> bool:
        """Verify hash-chain integrity with previous entry.
        
        Args:
            prev_entry: Previous audit log entry (None for first entry)
            
        Returns:
            True if chain integrity is valid
        """
        if prev_entry is None:
            expected_prev_hash = self.get_genesis_hash()
        else:
            expected_prev_hash = prev_entry.chain_hash

        # Check if prev_chain_hash matches expected
        if self.prev_chain_hash != expected_prev_hash:
            return False

        # Verify current chain_hash is correct
        expected_chain_hash = self.compute_chain_hash(
            self.prev_chain_hash,
            self.payload
        )
        return self.chain_hash == expected_chain_hash

    @property
    def is_system_action(self) -> bool:
        """Check if action was performed by system (no user)."""
        return self.actor_user_id is None

    @property
    def is_user_action(self) -> bool:
        """Check if action was performed by authenticated user."""
        return self.actor_user_id is not None

    def get_payload_field(self, field_path: str, default: Any = None) -> Any:
        """Get field from payload using dot notation.
        
        Args:
            field_path: Dot-separated path (e.g., 'user.email')
            default: Default value if field not found
            
        Returns:
            Field value or default
        """
        if not self.payload:
            return default

        try:
            value = self.payload
            for key in field_path.split('.'):
                value = value[key]
            return value
        except (KeyError, TypeError, AttributeError):
            return default

    def add_payload_field(self, field_path: str, value: Any) -> None:
        """Add field to payload using dot notation.
        
        Args:
            field_path: Dot-separated path (e.g., 'metadata.source')
            value: Value to set
        """
        if self.payload is None:
            self.payload = {}

        # Navigate to parent and set value
        current = self.payload
        keys = field_path.split('.')

        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        current[keys[-1]] = value
