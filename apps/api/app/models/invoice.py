"""Invoice model for billing and accounting - Task Master ERD compliant."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import (
    BigInteger, CheckConstraint, DateTime, Enum as SQLEnum, 
    ForeignKey, Index, String, func, text
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import Currency, InvoiceStatus

if TYPE_CHECKING:
    from .payment import Payment
    from .user import User


class Invoice(Base, TimestampMixin):
    """Customer invoices and billing records.
    
    ENTERPRISE DESIGN PRINCIPLES:
    - Monetary precision using amount_cents (BigInteger) to avoid floating-point errors
    - Multi-currency support with configurable constraints
    - Comprehensive audit trail and metadata storage
    - Optimal indexing for billing query patterns
    - Security-first approach with proper constraints
    """
    
    __tablename__ = "invoices"
    
    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    
    # Foreign keys with enterprise security (RESTRICT to prevent data loss)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    
    # Invoice identification (unique business identifier)
    number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True,
        comment="Unique invoice number for business identification"
    )
    
    # Financial details with cent precision for accuracy
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Invoice amount in smallest currency unit (cents)"
    )
    
    # Currency with multi-currency constraint support
    currency: Mapped[Currency] = mapped_column(
        SQLEnum(Currency, name="currency_enum"),
        nullable=False,
        server_default=text("'TRY'"),
        comment="Invoice currency code"
    )
    
    # Invoice lifecycle status
    status: Mapped[InvoiceStatus] = mapped_column(
        SQLEnum(InvoiceStatus, name="invoice_status_enum"),
        nullable=False,
        server_default=text("'DRAFT'"),
        index=True,
        comment="Current invoice status"
    )
    
    # Timestamps for billing workflow
    issued_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="When invoice was issued to customer"
    )
    
    due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="Payment due date"
    )
    
    # Flexible metadata storage for invoice details
    meta: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        server_default=text("'{}'"),
        comment="Invoice metadata: line items, tax details, etc."
    )
    
    # Relationships
    user: Mapped[User] = relationship(
        "User", 
        back_populates="invoices",
        lazy="select"
    )
    payments: Mapped[List[Payment]] = relationship(
        "Payment",
        back_populates="invoice",
        cascade="all, delete-orphan",
        lazy="select"
    )
    
    # Enterprise constraints and indexes
    __table_args__ = (
        # Multi-currency constraint: allows all currencies if multi_currency setting is on,
        # otherwise restricts to TRY only
        CheckConstraint(
            "("
            "current_setting('app.multi_currency', true)::text = 'on' "
            "OR currency = 'TRY'"
            ")",
            name="ck_invoices_currency_policy"
        ),
        
        # Financial integrity constraints
        CheckConstraint(
            "amount_cents >= 0",
            name="ck_invoices_amount_non_negative"
        ),
        
        # Business logic constraints
        CheckConstraint(
            "(issued_at IS NULL OR due_at IS NULL OR issued_at <= due_at)",
            name="ck_invoices_due_after_issued"
        ),
        
        # Optimized indexes for billing queries
        Index(
            "idx_invoices_user_status",
            "user_id", "status",
            postgresql_where="status IN ('SENT', 'OVERDUE', 'PARTIAL')"
        ),
        Index(
            "idx_invoices_issued_at",
            "issued_at",
            postgresql_where="issued_at IS NOT NULL"
        ),
        Index(
            "idx_invoices_due_at",
            "due_at",
            postgresql_where="due_at IS NOT NULL AND status NOT IN ('PAID', 'CANCELLED')"
        ),
    )
    
    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, number='{self.number}', amount_cents={self.amount_cents})>"
    
    def __str__(self) -> str:
        return f"Invoice {self.number}: {self.amount_decimal:.2f} {self.currency.value}"
    
    @property
    def amount_decimal(self) -> Decimal:
        """Convert cents to decimal amount for display with precision."""
        return Decimal(self.amount_cents) / Decimal('100')
    
    @property
    def is_overdue(self) -> bool:
        """Check if invoice is overdue."""
        if self.status in [InvoiceStatus.PAID, InvoiceStatus.CANCELLED]:
            return False
        if self.due_at is None:
            return False
        return datetime.now(timezone.utc) > self.due_at
    
    @property
    def paid_amount_cents(self) -> int:
        """Calculate total amount paid in cents."""
        # OPTIMIZATION: Direct enum comparison (more efficient than .value string comparison)
        from .enums import PaymentStatus
        return sum(
            payment.amount_cents for payment in self.payments
            if payment.status == PaymentStatus.COMPLETED
        )
    
    @property
    def balance_due_cents(self) -> int:
        """Calculate remaining balance in cents."""
        return self.amount_cents - self.paid_amount_cents
    
    @property
    def is_fully_paid(self) -> bool:
        """Check if invoice is fully paid."""
        return self.balance_due_cents <= 0
    
    def mark_as_sent(self, issued_at: Optional[datetime] = None) -> None:
        """Mark invoice as sent to customer."""
        self.status = InvoiceStatus.SENT
        self.issued_at = issued_at or datetime.now(timezone.utc)
    
    def mark_as_paid(self, paid_at: Optional[datetime] = None) -> None:
        """Mark invoice as fully paid."""
        if self.is_fully_paid:
            self.status = InvoiceStatus.PAID
            if self.meta is None:
                self.meta = {}
            self.meta['paid_at'] = (paid_at or datetime.now(timezone.utc)).isoformat()
    
    def add_line_item(
        self,
        description: str,
        quantity: int,
        unit_price_cents: int,
        tax_rate_percent: float = 20.0
    ) -> None:
        """Add a line item to invoice metadata."""
        if self.meta is None:
            self.meta = {'line_items': []}
        if 'line_items' not in self.meta:
            self.meta['line_items'] = []
            
        subtotal_cents = quantity * unit_price_cents
        # CRITICAL FIX: Use Decimal for precise tax calculations (no floating-point errors)
        tax_cents = int(
            (Decimal(str(subtotal_cents)) * Decimal(str(tax_rate_percent)) / Decimal('100'))
            .to_integral_value(rounding=ROUND_HALF_UP)
        )
        total_cents = subtotal_cents + tax_cents
        
        line_item = {
            'description': description,
            'quantity': quantity,
            'unit_price_cents': unit_price_cents,
            'tax_rate_percent': tax_rate_percent,
            'subtotal_cents': subtotal_cents,
            'tax_cents': tax_cents,
            'total_cents': total_cents
        }
        
        # Add line item with precision-calculated totals
        self.meta['line_items'].append(line_item)
        self.recalculate_amount()
    
    def recalculate_amount(self) -> None:
        """Recalculate total amount from line items."""
        if not self.meta or 'line_items' not in self.meta:
            return
            
        self.amount_cents = sum(
            item['total_cents'] for item in self.meta['line_items']
        )
    
    def calculate_tax_amount_cents(self, tax_rate_percent: float = 20.0) -> int:
        """Calculate tax amount using Decimal precision for financial accuracy.
        
        Args:
            tax_rate_percent: Tax rate as percentage (default: 20.0 for Turkish KDV)
            
        Returns:
            Tax amount in cents using precise Decimal calculations
        """
        if self.amount_cents <= 0:
            return 0
            
        # Use Decimal for precise financial calculations
        base_amount = Decimal(str(self.amount_cents))
        tax_rate = Decimal(str(tax_rate_percent))
        
        # Calculate tax with proper rounding
        tax_amount = (base_amount * tax_rate / Decimal('100')).to_integral_value(rounding=ROUND_HALF_UP)
        return int(tax_amount)
    
    def calculate_subtotal_from_total_cents(self, tax_rate_percent: float = 20.0) -> int:
        """Calculate subtotal from total amount (reverse tax calculation).
        
        Args:
            tax_rate_percent: Tax rate as percentage
            
        Returns:
            Subtotal amount in cents (excluding tax)
        """
        if self.amount_cents <= 0:
            return 0
            
        # Use Decimal for precise reverse tax calculation
        total_amount = Decimal(str(self.amount_cents))
        tax_rate = Decimal(str(tax_rate_percent))
        
        # Subtotal = Total / (1 + tax_rate/100)
        divisor = Decimal('1') + (tax_rate / Decimal('100'))
        subtotal = (total_amount / divisor).to_integral_value(rounding=ROUND_HALF_UP)
        return int(subtotal)
    
    def get_tax_breakdown(self, tax_rate_percent: float = 20.0) -> dict:
        """Get detailed tax breakdown for Turkish financial compliance.
        
        Args:
            tax_rate_percent: Tax rate as percentage
            
        Returns:
            Dictionary with subtotal, tax, and total amounts in cents
        """
        subtotal_cents = self.calculate_subtotal_from_total_cents(tax_rate_percent)
        tax_cents = self.amount_cents - subtotal_cents
        
        return {
            'subtotal_cents': subtotal_cents,
            'tax_cents': tax_cents,
            'total_cents': self.amount_cents,
            'tax_rate_percent': tax_rate_percent,
            'subtotal_decimal': Decimal(subtotal_cents) / Decimal('100'),
            'tax_decimal': Decimal(tax_cents) / Decimal('100'),
            'total_decimal': self.amount_decimal
        }