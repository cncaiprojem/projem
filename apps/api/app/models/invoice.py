"""
Invoice model for billing and accounting.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List

from sqlalchemy import (
    String, ForeignKey, Index, DateTime, Date,
    Numeric, CheckConstraint, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import InvoiceType, InvoiceStatus, Currency


class Invoice(Base, TimestampMixin):
    """Customer invoices and billing records."""
    
    __tablename__ = "invoices"
    
    # Primary key
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    
    # Foreign keys
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    
    # Invoice identification
    invoice_number: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        nullable=False,
        index=True
    )
    
    # Invoice type and status
    type: Mapped[InvoiceType] = mapped_column(
        SQLEnum(InvoiceType),
        nullable=False
    )
    status: Mapped[InvoiceStatus] = mapped_column(
        SQLEnum(InvoiceStatus),
        nullable=False,
        index=True
    )
    
    # Financial details
    currency: Mapped[Currency] = mapped_column(
        SQLEnum(Currency),
        nullable=False,
        default=Currency.TRY
    )
    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False
    )
    tax_rate: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("20.00")  # Turkish KDV
    )
    tax_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False
    )
    total: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False
    )
    
    # Line items
    line_items: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=[]
    )
    
    # Billing period
    billing_period_start: Mapped[Optional[date]] = mapped_column(Date)
    billing_period_end: Mapped[Optional[date]] = mapped_column(Date)
    
    # Payment terms
    due_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
        index=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    payment_method: Mapped[Optional[str]] = mapped_column(String(50))
    
    # Additional information
    notes: Mapped[Optional[str]] = mapped_column(String(1000))
    pdf_s3_key: Mapped[Optional[str]] = mapped_column(String(1024))
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="invoices")
    payments: Mapped[List["Payment"]] = relationship(
        "Payment",
        back_populates="invoice"
    )
    
    # Constraints and indexes
    __table_args__ = (
        CheckConstraint('currency IN (\'TRY\', \'USD\', \'EUR\')', 
                       name='ck_invoices_currency'),
        CheckConstraint('total >= 0', name='ck_invoices_total_positive'),
        CheckConstraint('tax_rate >= 0 AND tax_rate <= 100', 
                       name='ck_invoices_tax_rate_valid'),
        Index('idx_invoices_status', 'status',
              postgresql_where="status != 'paid'"),
        Index('idx_invoices_due_date', 'due_date',
              postgresql_where="status IN ('sent', 'overdue')"),
    )
    
    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, number={self.invoice_number}, total={self.total})>"
    
    @property
    def is_overdue(self) -> bool:
        """Check if invoice is overdue."""
        if self.status in [InvoiceStatus.PAID, InvoiceStatus.CANCELLED]:
            return False
        return date.today() > self.due_date
    
    @property
    def paid_amount(self) -> Decimal:
        """Calculate total amount paid."""
        return sum(
            p.amount for p in self.payments 
            if p.status == 'completed'
        )
    
    @property
    def balance_due(self) -> Decimal:
        """Calculate remaining balance."""
        return self.total - self.paid_amount
    
    def add_line_item(
        self,
        description: str,
        quantity: int,
        unit_price: Decimal,
        tax_rate: Optional[Decimal] = None
    ) -> dict:
        """
        Add a line item to the invoice.
        
        FINANCIAL PRECISION NOTE: All monetary values are stored as strings
        in JSONB to preserve precision and prevent floating-point rounding errors.
        This ensures accurate financial calculations for enterprise applications.
        """
        if tax_rate is None:
            tax_rate = self.tax_rate
            
        subtotal = quantity * unit_price
        tax = subtotal * (tax_rate / 100)
        total = subtotal + tax
        
        item = {
            'description': description,
            'quantity': quantity,
            'unit_price': str(unit_price),  # Store as string to preserve precision
            'tax_rate': str(tax_rate),      # Store as string to preserve precision
            'subtotal': str(subtotal),      # Store as string to preserve precision
            'tax': str(tax),               # Store as string to preserve precision
            'total': str(total)            # Store as string to preserve precision
        }
        
        if not isinstance(self.line_items, list):
            self.line_items = []
        self.line_items.append(item)
        
        # Recalculate totals
        self.recalculate_totals()
        
        return item
    
    def recalculate_totals(self):
        """Recalculate invoice totals from line items."""
        if not self.line_items:
            return
            
        self.subtotal = Decimal(
            sum(Decimal(str(item['subtotal'])) for item in self.line_items)
        )
        self.tax_amount = Decimal(
            sum(Decimal(str(item['tax'])) for item in self.line_items)
        )
        self.total = self.subtotal + self.tax_amount