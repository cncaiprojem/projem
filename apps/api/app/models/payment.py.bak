"""Payment model for transaction processing - Task Master ERD compliant."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, Enum as SQLEnum, 
    ForeignKey, Index, String, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import Currency, PaymentStatus

if TYPE_CHECKING:
    from .invoice import Invoice
    from .user import User


class Payment(Base, TimestampMixin):
    """Payment transactions and records.
    
    ENTERPRISE DESIGN PRINCIPLES:
    - Monetary precision using amount_cents (BigInteger) to avoid floating-point errors
    - Provider integration with unique reference tracking
    - Multi-currency support with configurable constraints
    - Comprehensive audit trail and metadata storage
    - Optimal indexing for payment query patterns
    - Security-first approach with proper constraints
    """
    
    __tablename__ = "payments"
    
    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    
    # Foreign keys with enterprise security (RESTRICT to prevent data loss)
    invoice_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    
    # User who initiated the payment (derived from invoice, but cached for query performance)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="User who owns the invoice and payment"
    )
    
    # Payment provider integration
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Payment provider identifier (stripe, iyzico, etc.)"
    )
    
    provider_ref: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Unique provider transaction reference"
    )
    
    # Financial details with cent precision for accuracy
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Payment amount in smallest currency unit (cents)"
    )
    
    # Currency with multi-currency constraint support
    currency: Mapped[Currency] = mapped_column(
        SQLEnum(Currency, name="currency_enum"),
        nullable=False,
        server_default=text("'TRY'"),
        comment="Payment currency code"
    )
    
    # Payment lifecycle status
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus, name="payment_status_enum"),
        nullable=False,
        server_default=text("'PENDING'"),
        index=True,
        comment="Current payment status"
    )
    
    # Payment completion timestamp
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When payment was successfully completed"
    )
    
    # Flexible metadata storage for payment details
    meta: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        server_default=text("'{}'"),
        comment="Payment metadata: provider details, transaction info, etc."
    )
    
    # Relationships
    invoice: Mapped[Invoice] = relationship(
        "Invoice",
        back_populates="payments",
        lazy="select"
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="payments",
        lazy="select"
    )
    
    # Enterprise constraints and indexes
    __table_args__ = (
        # Composite unique constraint: provider + provider_ref uniqueness across providers
        # CRITICAL FIX: Prevents duplicate payments across different providers
        # Each provider can have their own reference namespace
        UniqueConstraint(
            "provider", "provider_ref",
            name="uq_payments_provider_provider_ref"
        ),
        
        # Multi-currency constraint: allows all currencies if multi_currency setting is on,
        # otherwise restricts to TRY only
        CheckConstraint(
            "("
            "current_setting('app.multi_currency', true)::text = 'on' "
            "OR currency = 'TRY'"
            ")",
            name="ck_payments_currency_policy"
        ),
        
        # Financial integrity constraints
        CheckConstraint(
            "amount_cents > 0",
            name="ck_payments_amount_positive"
        ),
        
        # Business logic constraints
        CheckConstraint(
            "(status != 'COMPLETED' OR paid_at IS NOT NULL)",
            name="ck_payments_completed_has_paid_at"
        ),
        
        # Optimized indexes for payment queries
        Index(
            "idx_payments_invoice_status",
            "invoice_id", "status",
            postgresql_where="status IN ('PENDING', 'PROCESSING')"
        ),
        Index(
            "idx_payments_user_status",
            "user_id", "status",
            postgresql_where="status IN ('PENDING', 'PROCESSING', 'COMPLETED')"
        ),
        Index(
            "idx_payments_paid_at",
            "paid_at",
            postgresql_where="paid_at IS NOT NULL"
        ),
        Index(
            "idx_payments_provider",
            "provider", "status",
            postgresql_where="status = 'PENDING'"
        ),
    )
    
    def __repr__(self) -> str:
        return f"<Payment(id={self.id}, provider_ref='{self.provider_ref}', amount_cents={self.amount_cents})>"
    
    def __str__(self) -> str:
        return f"Payment {self.provider_ref}: {self.amount_decimal:.2f} {self.currency.value}"
    
    @property
    def amount_decimal(self) -> Decimal:
        """Convert cents to decimal amount for display with precision."""
        return Decimal(self.amount_cents) / Decimal('100')
    
    @property
    def is_successful(self) -> bool:
        """Check if payment was successful."""
        # OPTIMIZATION: Direct enum comparison for efficiency
        return self.status == PaymentStatus.COMPLETED
    
    @property
    def is_pending(self) -> bool:
        """Check if payment is still pending."""
        return self.status in [PaymentStatus.PENDING, PaymentStatus.PROCESSING]
    
    @property
    def is_failed(self) -> bool:
        """Check if payment failed."""
        return self.status in [PaymentStatus.FAILED, PaymentStatus.CANCELLED]
    
    def mark_as_completed(self, paid_at: Optional[datetime] = None) -> None:
        """Mark payment as successfully completed."""
        self.status = PaymentStatus.COMPLETED
        self.paid_at = paid_at or datetime.now(timezone.utc)
        
        # Store completion details in metadata
        if self.meta is None:
            self.meta = {}
        self.meta['completed_at'] = self.paid_at.isoformat()
    
    def mark_as_failed(self, reason: str, error_code: Optional[str] = None) -> None:
        """Mark payment as failed with reason."""
        self.status = PaymentStatus.FAILED
        
        # Store failure details in metadata
        if self.meta is None:
            self.meta = {}
        self.meta['failure'] = {
            'reason': reason,
            'error_code': error_code,
            'failed_at': datetime.now(timezone.utc).isoformat()
        }
    
    def add_provider_metadata(self, key: str, value: any) -> None:
        """Add provider-specific metadata."""
        if self.meta is None:
            self.meta = {}
        if 'provider_data' not in self.meta:
            self.meta['provider_data'] = {}
        
        self.meta['provider_data'][key] = value
    
    def get_provider_metadata(self, key: str, default: any = None) -> any:
        """Get provider-specific metadata."""
        if not self.meta or 'provider_data' not in self.meta:
            return default
        return self.meta['provider_data'].get(key, default)