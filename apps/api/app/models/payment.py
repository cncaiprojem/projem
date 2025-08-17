"""
Payment model for transaction processing.
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    String, ForeignKey, Index, DateTime,
    Numeric, CheckConstraint, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import PaymentMethod, PaymentStatus, Currency


class Payment(Base, TimestampMixin):
    """Payment transactions and records."""
    
    __tablename__ = "payments"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Foreign keys
    invoice_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    
    # Payment provider
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False
    )
    provider_ref: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )
    
    # Payment details
    method: Mapped[PaymentMethod] = mapped_column(
        SQLEnum(PaymentMethod),
        nullable=False
    )
    currency: Mapped[Currency] = mapped_column(
        SQLEnum(Currency),
        nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False
    )
    fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0.00")
    )
    
    # Payment status
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus),
        nullable=False,
        index=True
    )
    
    # Provider metadata (renamed to avoid SQLAlchemy conflict)
    payment_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, name="metadata")
    
    # Refund information
    refund_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00")
    )
    refund_reason: Mapped[Optional[str]] = mapped_column(String(500))
    
    # Processing timestamp
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    
    # Relationships
    invoice: Mapped[Optional["Invoice"]] = relationship(
        "Invoice",
        back_populates="payments"
    )
    user: Mapped["User"] = relationship("User", back_populates="payments")
    
    # Constraints and indexes
    __table_args__ = (
        CheckConstraint('currency IN (\'TRY\', \'USD\', \'EUR\')',
                       name='ck_payments_currency'),
        CheckConstraint('amount > 0', name='ck_payments_amount_positive'),
        CheckConstraint('fee >= 0', name='ck_payments_fee_non_negative'),
        CheckConstraint('refund_amount >= 0 AND refund_amount <= amount',
                       name='ck_payments_refund_valid'),
        Index('idx_payments_invoice_id', 'invoice_id',
              postgresql_where='invoice_id IS NOT NULL'),
        Index('idx_payments_status', 'status',
              postgresql_where="status = 'pending'"),
    )
    
    def __repr__(self) -> str:
        return f"<Payment(id={self.id}, amount={self.amount}, status={self.status.value})>"
    
    @property
    def net_amount(self) -> Decimal:
        """Calculate net amount after fees."""
        return self.amount - self.fee
    
    @property
    def is_successful(self) -> bool:
        """Check if payment was successful."""
        return self.status == PaymentStatus.COMPLETED
    
    @property
    def is_refunded(self) -> bool:
        """Check if payment has been refunded."""
        return self.refund_amount > 0
    
    @property
    def is_fully_refunded(self) -> bool:
        """Check if payment has been fully refunded."""
        return self.refund_amount == self.amount
    
    def process_refund(
        self,
        amount: Decimal,
        reason: str,
        provider_ref: str
    ) -> bool:
        """
        Process a refund for this payment.
        
        FINANCIAL PRECISION & SECURITY NOTE: Refund amounts are stored as strings
        to preserve decimal precision. Timestamps use timezone-aware UTC to ensure
        consistent audit trails across different deployment environments.
        """
        if self.status != PaymentStatus.COMPLETED:
            raise ValueError("Can only refund completed payments")
            
        if amount <= 0:
            raise ValueError("Refund amount must be positive")
            
        if self.refund_amount + amount > self.amount:
            raise ValueError("Refund amount exceeds payment amount")
        
        self.refund_amount += amount
        self.refund_reason = reason
        
        # Update status based on refund amount
        if self.is_fully_refunded:
            self.status = PaymentStatus.REFUNDED
        else:
            self.status = PaymentStatus.PARTIAL_REFUND
        
        # Store refund reference in payment metadata
        if not self.payment_metadata:
            self.payment_metadata = {}
        if 'refunds' not in self.payment_metadata:
            self.payment_metadata['refunds'] = []
        
        self.payment_metadata['refunds'].append({
            'amount': str(amount),  # Store as string to preserve precision
            'reason': reason,
            'provider_ref': provider_ref,
            'timestamp': datetime.now(timezone.utc).isoformat()
        })
        
        return True