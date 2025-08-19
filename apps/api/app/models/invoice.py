"""
Invoice model for Task 4.4: Ultra-enterprise invoice numbering, VAT calculation, and Turkish compliance.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING, Optional, List

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    Index,
    String,
    Text,
    text,
    CHAR,
    NUMERIC,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin
from .enums import Currency, PaidStatus

if TYPE_CHECKING:
    from .user import User
    from .license import License
    from .payment import Payment


class Invoice(Base, TimestampMixin):
    """
    Task 4.4: Ultra-enterprise invoice model with Turkish KDV compliance.

    Features:
    - Invoice numbering scheme: 'YYYYMM-SEQ-CNCAI'
    - 20% Turkish VAT calculation with half-up rounding
    - Currency fixed to TRY (Turkish Lira)
    - Payment status tracking
    - License and user associations
    """

    __tablename__ = "invoices"

    # Primary key
    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="Invoice primary key"
    )

    # Foreign keys - Task 4.4 specification
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="User who owns this invoice",
    )

    license_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("licenses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="License this invoice is for",
    )

    # Invoice identification - Task 4.4 numbering scheme
    number: Mapped[str] = mapped_column(
        String(20),  # 'YYYYMM-SEQ-CNCAI' fits in 20 chars
        unique=True,
        nullable=False,
        index=True,
        comment="Unique invoice number: YYYYMM-SEQ-CNCAI format",
    )

    # Financial amounts - Task 4.4 specification with NUMERIC(12,2) precision
    amount: Mapped[Decimal] = mapped_column(
        NUMERIC(12, 2), nullable=False, comment="Invoice base amount before VAT"
    )

    # Currency - Task 4.4: Fixed to TRY
    currency: Mapped[str] = mapped_column(
        CHAR(3),
        nullable=False,
        server_default=text("'TRY'"),
        comment="Invoice currency - fixed to TRY",
    )

    # VAT amount - Task 4.4: Calculated at 20%
    vat: Mapped[Decimal] = mapped_column(
        NUMERIC(12, 2), nullable=False, comment="VAT amount at 20% Turkish KDV rate"
    )

    # Total amount - Task 4.4: amount + vat
    total: Mapped[Decimal] = mapped_column(
        NUMERIC(12, 2), nullable=False, comment="Total amount including VAT"
    )

    # Payment status - Task 4.4 specification
    paid_status: Mapped[PaidStatus] = mapped_column(
        SQLEnum(PaidStatus, name="paid_status_enum"),
        nullable=False,
        server_default=text("'unpaid'"),
        index=True,
        comment="Payment status: unpaid, pending, paid, failed, refunded",
    )

    # Issued timestamp - Task 4.4: Used in numbering scheme
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        index=True,
        comment="When invoice was issued (UTC)",
    )

    # PDF generation URL - Task 4.4 specification
    pdf_url: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="URL to generated PDF invoice"
    )

    # Provider payment ID - Task 4.4 specification
    provider_payment_id: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="External payment provider transaction ID"
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="invoices", lazy="select")

    license: Mapped["License"] = relationship("License", back_populates="invoices", lazy="select")

    # Payment relationship
    payments: Mapped[list["Payment"]] = relationship(
        "Payment", back_populates="invoice", lazy="select"
    )

    # Ultra-enterprise constraints and indexes - Task 4.4
    __table_args__ = (
        # Currency constraint - Task 4.4: Fixed to TRY only
        CheckConstraint("currency = 'TRY'", name="ck_invoices_currency_try_only"),
        # Financial integrity constraints - Task 4.4
        CheckConstraint("amount >= 0", name="ck_invoices_amount_non_negative"),
        CheckConstraint("vat >= 0", name="ck_invoices_vat_non_negative"),
        CheckConstraint("total >= 0", name="ck_invoices_total_non_negative"),
        # VAT calculation constraint - Task 4.4: total = amount + vat
        CheckConstraint("total = amount + vat", name="ck_invoices_total_equals_amount_plus_vat"),
        # Invoice numbering format constraint - Task 4.4
        CheckConstraint("number ~ '^[0-9]{6}-[0-9]{6}-CNCAI$'", name="ck_invoices_number_format"),
        # Performance indexes for billing queries
        Index("idx_invoices_user_paid_status", "user_id", "paid_status"),
        Index("idx_invoices_license_paid_status", "license_id", "paid_status"),
        Index("idx_invoices_issued_at_desc", "issued_at"),
        Index("idx_invoices_number_unique", "number", unique=True),
        # Partial index for unpaid invoices
        Index(
            "idx_invoices_unpaid", "user_id", "issued_at", postgresql_where="paid_status = 'unpaid'"
        ),
    )

    def __repr__(self) -> str:
        return f"<Invoice(id={self.id}, number='{self.number}', amount={self.amount}, total={self.total})>"

    def __str__(self) -> str:
        return f"Invoice {self.number}: {self.total:.2f} {self.currency}"

    @property
    def is_paid(self) -> bool:
        """Check if invoice is fully paid."""
        return self.paid_status == PaidStatus.PAID

    @property
    def is_unpaid(self) -> bool:
        """Check if invoice is unpaid."""
        return self.paid_status == PaidStatus.UNPAID

    @property
    def is_overdue(self) -> bool:
        """
        Check if invoice is overdue based on due date.
        For now, invoices are due 30 days after issuance.
        This can be customized based on business requirements.
        """
        if self.paid_status == PaidStatus.PAID:
            return False

        # Calculate due date (30 days after issuance)
        due_date = self.issued_at + timedelta(days=30)
        now = datetime.now(timezone.utc)

        return now > due_date and self.paid_status == PaidStatus.UNPAID

    @classmethod
    def calculate_vat(cls, amount: Decimal) -> Decimal:
        """
        Task 4.4: Calculate 20% Turkish KDV with half-up rounding.

        Formula: vat = round(amount * 0.20, 2) with ROUND_HALF_UP
        """
        vat_rate = Decimal("0.20")
        vat_amount = amount * vat_rate
        return vat_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def calculate_total(cls, amount: Decimal, vat: Decimal) -> Decimal:
        """
        Task 4.4: Calculate total amount.

        Formula: total = amount + vat
        """
        return amount + vat

    @classmethod
    def create_invoice_amounts(cls, base_amount: Decimal) -> dict:
        """
        Task 4.4: Create invoice with proper VAT calculation.

        Returns dict with amount, vat, total calculated per specification.
        """
        amount = base_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        vat = cls.calculate_vat(amount)
        total = cls.calculate_total(amount, vat)

        return {"amount": amount, "vat": vat, "total": total}

    def mark_as_paid(self, provider_payment_id: Optional[str] = None) -> None:
        """Mark invoice as paid with optional provider payment ID."""
        self.paid_status = PaidStatus.PAID
        if provider_payment_id:
            self.provider_payment_id = provider_payment_id

    def mark_as_failed(self, reason: Optional[str] = None) -> None:
        """Mark payment as failed."""
        self.paid_status = PaidStatus.FAILED
        # Could store reason in provider_payment_id field or extend model

    def mark_as_pending(self, provider_payment_id: Optional[str] = None) -> None:
        """Mark payment as pending processing."""
        self.paid_status = PaidStatus.PENDING
        if provider_payment_id:
            self.provider_payment_id = provider_payment_id
