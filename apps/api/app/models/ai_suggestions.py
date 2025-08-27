"""AI suggestion records with Turkish KVKK compliance.

Task 7.15: AI-powered model generation suggestions with privacy compliance
and cost tracking.
"""

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    String, BigInteger, Integer, ForeignKey, DateTime, UniqueConstraint, Index, Text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .user import User


class AISuggestion(Base, TimestampMixin):
    """AI suggestion records with Turkish KVKK compliance.
    
    Task 7.15 Requirements:
    - Store AI prompts and responses for model generation
    - Mask PII in prompts for KVKK compliance
    - Track costs and token usage for billing
    - Set retention policies for data privacy
    """
    
    __tablename__ = "ai_suggestions"
    
    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
        autoincrement=True
    )
    
    # Core fields
    prompt: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="User prompt (PII masked for KVKK compliance)"
    )
    response: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="AI response in structured format"
    )
    
    # Foreign keys
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_ai_suggestions_user_id"),
        nullable=False,
        index=True
    )
    
    # Request tracking
    request_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Unique request identifier for tracing"
    )
    
    # AI model information
    model_name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="AI model used for generation"
    )
    
    # Token usage and costs
    prompt_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of tokens in prompt"
    )
    response_tokens: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Number of tokens in response"
    )
    total_cost_cents: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="Total cost in cents for this request"
    )
    
    # Metadata
    metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional metadata and context"
    )
    
    # KVKK compliance
    retention_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="KVKK compliance: When this record should be deleted"
    )
    
    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="ai_suggestions",
        foreign_keys=[user_id]
    )
    
    # Table constraints
    __table_args__ = (
        UniqueConstraint('request_id', name='uq_ai_suggestions_request_id'),
        Index('idx_ai_suggestions_user_id', 'user_id'),
        Index('idx_ai_suggestions_request_id', 'request_id'),
        Index('idx_ai_suggestions_created_at', 'created_at'),
        Index('idx_ai_suggestions_retention_expires', 'retention_expires_at',
              postgresql_where='retention_expires_at IS NOT NULL'),
        Index('idx_ai_suggestions_response', 'response',
              postgresql_using='gin'),
        Index('idx_ai_suggestions_metadata', 'metadata',
              postgresql_using='gin',
              postgresql_where='metadata IS NOT NULL'),
        {'comment': 'AI suggestion records with Turkish KVKK compliance'}
    )
    
    def __repr__(self) -> str:
        return f"<AISuggestion(id={self.id}, request_id={self.request_id}, model={self.model_name})>"
    
    def __str__(self) -> str:
        return f"AI Suggestion #{self.id} - {self.request_id}"
    
    @property
    def total_tokens(self) -> Optional[int]:
        """Calculate total tokens used."""
        if self.prompt_tokens is None or self.response_tokens is None:
            return None
        return self.prompt_tokens + self.response_tokens
    
    @property
    def cost_dollars(self) -> Optional[float]:
        """Get cost in dollars."""
        if self.total_cost_cents is None:
            return None
        return self.total_cost_cents / 100.0
    
    @property
    def is_expired(self) -> bool:
        """Check if retention period has expired."""
        if self.retention_expires_at is None:
            return False
        from datetime import datetime, timezone
        return datetime.now(timezone.utc) > self.retention_expires_at
    
    def mask_pii(self, text: str) -> str:
        """Mask PII in text for KVKK compliance.
        
        This is a placeholder - implement actual PII masking logic
        based on Turkish KVKK requirements.
        """
        # TODO: Implement actual PII masking
        # - Email addresses
        # - Phone numbers
        # - Turkish ID numbers
        # - Names
        # - Addresses
        return text
    
    def set_retention_period(self, days: int = 90) -> None:
        """Set retention expiration date.
        
        Default 90 days for AI suggestions per KVKK guidelines.
        """
        from datetime import timedelta, timezone
        self.retention_expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    
    def get_structured_response(self, key: str = None):
        """Get structured data from response."""
        if key:
            return self.response.get(key)
        return self.response
    
    def add_metadata(self, key: str, value: any) -> None:
        """Add metadata entry."""
        if self.metadata is None:
            self.metadata = {}
        self.metadata[key] = value
        # Mark field as modified for SQLAlchemy
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(self, "metadata")