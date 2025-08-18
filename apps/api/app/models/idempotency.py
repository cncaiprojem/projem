"""
Task 4.2: Idempotency Record Model
Ultra-enterprise banking grade idempotency tracking for API operations.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any
from uuid import UUID

from sqlalchemy import (
    Column, String, Integer, DateTime, JSON, 
    UniqueConstraint, Index, Text
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID as PGUUID

from ..db import Base


class IdempotencyRecord(Base):
    """
    Idempotency record for tracking API requests and preventing duplicate operations.
    
    Ultra-Enterprise Features:
    - Unique constraint on user_id + idempotency_key
    - Response data storage for consistent replay
    - TTL support for automatic cleanup
    - Turkish KVKV compliance with data retention
    """
    
    __tablename__ = "idempotency_records"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    
    # User identification
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
        index=True,
        comment="User who made the request"
    )
    
    # Idempotency key from header
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Unique key from Idempotency-Key header"
    )
    
    # Request information
    endpoint: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="API endpoint path"
    )
    
    method: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="HTTP method (POST, PUT, etc.)"
    )
    
    # Response storage
    response_status: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="HTTP response status code"
    )
    
    response_data: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        comment="Stored response data for replay"
    )
    
    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When the request was first processed"
    )
    
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="When this idempotency record expires (24 hours by default)"
    )
    
    # Table constraints
    __table_args__ = (
        UniqueConstraint(
            'user_id', 'idempotency_key',
            name='uq_user_idempotency_key'
        ),
        Index(
            'ix_idempotency_expires',
            'expires_at',
            postgresql_where='expires_at > NOW()'
        ),
        {'comment': 'Idempotency tracking for API operations with Turkish KVKV compliance'}
    )
    
    def __repr__(self) -> str:
        return (
            f"<IdempotencyRecord("
            f"id={self.id}, "
            f"user_id={self.user_id}, "
            f"key={self.idempotency_key[:20]}..., "
            f"endpoint={self.endpoint}"
            f")>"
        )
    
    def is_expired(self) -> bool:
        """Check if this idempotency record has expired."""
        return datetime.now(timezone.utc) > self.expires_at
    
    @classmethod
    def create_expiry_time(cls, hours: int = 24) -> datetime:
        """Create an expiry time for idempotency records."""
        from datetime import timedelta
        return datetime.now(timezone.utc) + timedelta(hours=hours)