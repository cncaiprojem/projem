"""AI suggestion records with Turkish KVKK compliance.

Task 7.15: AI-powered model generation suggestions with privacy compliance
and cost tracking.
"""

import re
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
        
        Masks personal information according to Turkish KVKK requirements:
        - Email addresses
        - Phone numbers (Turkish and international)
        - Turkish ID numbers (TC Kimlik)
        - Credit card numbers
        - IBAN numbers
        - Common Turkish names
        - Addresses
        """
        if not text:
            return text
            
        masked_text = text
        
        # Email addresses - preserve first and last chars for better UX
        email_pattern = r'\b([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b'
        
        def mask_email(match):
            local = match.group(1)
            domain = match.group(2)
            
            # Handle short emails (<=2 chars) specially
            if len(local) <= 2:
                return f"***@{domain}"
            else:
                # Preserve first and last characters
                return f"{local[0]}***{local[-1]}@{domain}"
        
        masked_text = re.sub(
            email_pattern,
            mask_email,
            masked_text,
            flags=re.IGNORECASE
        )
        
        # Turkish phone numbers (various formats) - optimized with single regex
        # Formats: +90 5xx xxx xxxx, 0 5xx xxx xxxx, 5xx xxx xxxx, etc.
        turkish_phone_patterns = [
            r'\+90\s*\d{3}\s*\d{3}\s*\d{2}\s*\d{2}',  # +90 5xx xxx xx xx
            r'\+90\s*\d{10}',                           # +905xxxxxxxxx
            r'0\s*5\d{2}\s*\d{3}\s*\d{2}\s*\d{2}',     # 0 5xx xxx xx xx
            r'05\d{9}',                                 # 05xxxxxxxxx
            r'5\d{2}\s*\d{3}\s*\d{2}\s*\d{2}',         # 5xx xxx xx xx
            r'5\d{9}',                                  # 5xxxxxxxxx
            r'\(\d{3}\)\s*\d{3}[-\s]?\d{2}[-\s]?\d{2}' # (5xx) xxx-xx-xx
        ]
        
        # Combine all phone patterns into a single regex for performance
        combined_phone_pattern = '|'.join(turkish_phone_patterns)
        masked_text = re.sub(combined_phone_pattern, '***-***-****', masked_text)
        
        # Turkish ID numbers (TC Kimlik No) - 11 digits
        tc_kimlik_pattern = r'\b\d{11}\b'
        masked_text = re.sub(tc_kimlik_pattern, '***********', masked_text)
        
        # Credit card numbers (16 digits with optional spaces/dashes)
        credit_card_pattern = r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b'
        masked_text = re.sub(credit_card_pattern, '****-****-****-****', masked_text)
        
        # IBAN numbers (Turkish IBAN format: TR + 24 digits)
        iban_pattern = r'\bTR\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b'
        masked_text = re.sub(
            iban_pattern,
            lambda m: f"TR** **** **** **** **** {m.group()[-6:-2]} {m.group()[-2:]}",
            masked_text,
            flags=re.IGNORECASE
        )
        
        # Common Turkish names (sample list - can be extended)
        turkish_names = [
            'Mehmet', 'Ahmet', 'Mustafa', 'Ali', 'Hasan', 'Hüseyin', 'İbrahim',
            'Fatma', 'Ayşe', 'Emine', 'Hatice', 'Zeynep', 'Elif', 'Meryem',
            'Ömer', 'Osman', 'Ramazan', 'Bekir', 'Murat', 'Serkan', 'Emre',
            'Özlem', 'Dilek', 'Sibel', 'Aslı', 'Gülşen', 'Şerife', 'Filiz'
        ]
        
        # Build single optimized regex pattern for all names
        # This is much more efficient than looping through each name
        escaped_names = [re.escape(name) for name in turkish_names]
        names_pattern = r'\b(' + '|'.join(escaped_names) + r')\s+([A-ZÇĞİÖŞÜ][a-zçğıöşü]+)\b'
        
        # Use replacement function to properly mask matched names
        def mask_name(match):
            first_name = match.group(1)
            # Use the actual matched first name, not loop variable
            return f"{first_name[0]}*** ***"
        
        masked_text = re.sub(
            names_pattern,
            mask_name,
            masked_text,
            flags=re.IGNORECASE
        )
        
        # Turkish address components (street names, mahalle, sokak, etc.) - optimized
        address_patterns = [
            r'\b\d+\.\s*(Sokak|Sk\.|Cadde|Cad\.|Mahalle|Mah\.)',
            r'\b(Sokak|Cadde|Mahalle|Bulvar|Blv\.)\s+No\s*:\s*\d+',
            r'\bDaire\s*:\s*\d+',
            r'\bKat\s*:\s*\d+'
        ]
        
        # Combine all address patterns into a single regex for performance
        combined_address_pattern = '|'.join(address_patterns)
        masked_text = re.sub(combined_address_pattern, '*** ***', masked_text, flags=re.IGNORECASE)
        
        return masked_text
    
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