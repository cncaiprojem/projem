"""
Financial schemas for invoices and payments with enterprise precision.

These schemas implement Gemini Code Assist feedback fixes:
1. Decimal validation for all monetary amounts
2. Turkish financial regulation compliance
3. Enterprise-grade validation patterns
4. Multi-currency support with constraints
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.types import PositiveInt

from ..models.enums import Currency, InvoiceStatus, PaymentStatus


class MonetaryAmount(BaseModel):
    """Enterprise monetary amount with precision validation."""

    amount_cents: PositiveInt = Field(
        ..., description="Amount in smallest currency unit (cents) for precision", example=12345
    )
    currency: Currency = Field(default=Currency.TRY, description="Currency code")

    @property
    def amount_decimal(self) -> Decimal:
        """Convert cents to decimal amount with precision."""
        return Decimal(self.amount_cents) / Decimal("100")

    @field_validator("amount_cents")
    @classmethod
    def validate_amount_cents(cls, v: int) -> int:
        """ULTRA ENTERPRISE VALIDATION: Validate monetary amount with strict bounds."""
        # Reject zero or negative amounts immediately
        if v <= 0:
            raise ValueError("Amount must be positive (greater than 0 cents)")

        # Ultra-strict minimum check (1 cent minimum)
        if v < 1:
            raise ValueError("Amount must be at least 1 cent")

        # Maximum amount check for financial safety (100 million TRY)
        if v > 10_000_000_000:  # 100,000,000.00 in cents
            raise ValueError("Amount exceeds maximum allowed value (100,000,000.00)")

        # Additional business rule validation for suspicious amounts
        if v > 1_000_000_000:  # 10 million TRY warning threshold
            # Log warning for amounts over 10 million (could be data entry error)
            import logging

            logging.warning(f"Large monetary amount detected: {v} cents ({v / 100:.2f})")

        return v

    def to_display_string(self) -> str:
        """Format amount for display."""
        return f"{self.amount_decimal:.2f} {self.currency.value}"


class TaxCalculation(BaseModel):
    """Turkish KDV tax calculation with precision."""

    subtotal_cents: PositiveInt = Field(..., description="Subtotal amount before tax (cents)")
    tax_cents: PositiveInt = Field(..., description="Tax amount (cents)")
    total_cents: PositiveInt = Field(..., description="Total amount including tax (cents)")
    tax_rate_percent: Decimal = Field(
        default=Decimal("20.0"),
        description="Tax rate percentage (default: 20% KDV)",
        ge=Decimal("0"),
        le=Decimal("100"),
    )

    @property
    def subtotal_decimal(self) -> Decimal:
        """Subtotal as decimal."""
        return Decimal(self.subtotal_cents) / Decimal("100")

    @property
    def tax_decimal(self) -> Decimal:
        """Tax as decimal."""
        return Decimal(self.tax_cents) / Decimal("100")

    @property
    def total_decimal(self) -> Decimal:
        """Total as decimal."""
        return Decimal(self.total_cents) / Decimal("100")

    @field_validator("tax_rate_percent")
    @classmethod
    def validate_tax_rate(cls, v: Decimal) -> Decimal:
        """ULTRA ENTERPRISE VALIDATION: Validate tax rate with Turkish compliance."""
        # Standard Turkish KDV rates validation
        valid_turkish_rates = [
            Decimal("0"),  # Tax-exempt
            Decimal("1"),  # Special rate
            Decimal("10"),  # Reduced rate
            Decimal("20"),  # Standard rate
            Decimal("25"),  # Higher rate (rare)
        ]

        # Allow common international rates but warn
        if v not in valid_turkish_rates and v not in [
            Decimal("5"),
            Decimal("15"),
            Decimal("18"),
            Decimal("21"),
            Decimal("24"),
        ]:
            if v > Decimal("50"):
                raise ValueError(f"Tax rate {v}% exceeds reasonable maximum (50%)")
            import logging

            logging.warning(f"Non-standard tax rate detected: {v}% (not standard Turkish KDV)")

        return v

    @model_validator(mode="after")
    def validate_tax_calculation(self) -> "TaxCalculation":
        """ULTRA ENTERPRISE VALIDATION: Comprehensive tax calculation integrity checks."""
        # Basic arithmetic validation
        if self.subtotal_cents + self.tax_cents != self.total_cents:
            raise ValueError(
                f"Tax calculation error: subtotal ({self.subtotal_cents}) + tax ({self.tax_cents}) "
                f"= {self.subtotal_cents + self.tax_cents} ≠ total ({self.total_cents})"
            )

        # Validate tax calculation precision using Decimal arithmetic
        expected_tax = int(
            (Decimal(str(self.subtotal_cents)) * self.tax_rate_percent / Decimal("100")).quantize(
                Decimal("1"), rounding="ROUND_HALF_UP"
            )
        )

        # Allow maximum 1 cent difference due to rounding
        tax_difference = abs(self.tax_cents - expected_tax)
        if tax_difference > 1:
            raise ValueError(
                f"Tax calculation precision error: expected {expected_tax} cents "
                f"({self.tax_rate_percent}% of {self.subtotal_cents}), got {self.tax_cents} cents "
                f"(difference: {tax_difference} cents exceeds 1 cent tolerance)"
            )

        # Validate reasonable tax ratios (tax should not exceed subtotal for normal rates)
        if self.tax_rate_percent <= Decimal("50") and self.tax_cents > self.subtotal_cents:
            raise ValueError(
                f"Tax amount ({self.tax_cents}) exceeds subtotal ({self.subtotal_cents}) "
                f"for rate {self.tax_rate_percent}% - possible calculation error"
            )

        return self


class InvoiceLineItem(BaseModel):
    """Invoice line item with precise calculations."""

    description: str = Field(..., min_length=1, max_length=500, description="Line item description")
    quantity: PositiveInt = Field(..., description="Quantity of items")
    unit_price_cents: PositiveInt = Field(..., description="Unit price in cents")
    tax_rate_percent: Decimal = Field(
        default=Decimal("20.0"),
        description="Tax rate percentage",
        ge=Decimal("0"),
        le=Decimal("100"),
    )
    subtotal_cents: PositiveInt = Field(..., description="Line subtotal (quantity * unit_price)")
    tax_cents: PositiveInt = Field(..., description="Line tax amount")
    total_cents: PositiveInt = Field(..., description="Line total (subtotal + tax)")

    @property
    def unit_price_decimal(self) -> Decimal:
        """Unit price as decimal."""
        return Decimal(self.unit_price_cents) / Decimal("100")

    @property
    def subtotal_decimal(self) -> Decimal:
        """Subtotal as decimal."""
        return Decimal(self.subtotal_cents) / Decimal("100")

    @property
    def tax_decimal(self) -> Decimal:
        """Tax as decimal."""
        return Decimal(self.tax_cents) / Decimal("100")

    @property
    def total_decimal(self) -> Decimal:
        """Total as decimal."""
        return Decimal(self.total_cents) / Decimal("100")

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        """ULTRA ENTERPRISE VALIDATION: Validate quantity bounds."""
        if v <= 0:
            raise ValueError("Quantity must be positive")
        if v > 1_000_000:  # Reasonable maximum for line items
            raise ValueError("Quantity exceeds reasonable maximum (1,000,000)")
        return v

    @field_validator("unit_price_cents")
    @classmethod
    def validate_unit_price(cls, v: int) -> int:
        """ULTRA ENTERPRISE VALIDATION: Validate unit price bounds."""
        if v <= 0:
            raise ValueError("Unit price must be positive")
        if v > 100_000_000:  # 1 million TRY per unit maximum
            raise ValueError("Unit price exceeds reasonable maximum (1,000,000.00)")
        return v

    @model_validator(mode="after")
    def validate_line_calculations(self) -> "InvoiceLineItem":
        """ULTRA ENTERPRISE VALIDATION: Comprehensive line item calculation validation."""
        # Critical arithmetic validation: subtotal = quantity * unit_price
        expected_subtotal = self.quantity * self.unit_price_cents
        if self.subtotal_cents != expected_subtotal:
            raise ValueError(
                f"Subtotal calculation error: {self.quantity} × {self.unit_price_cents} "
                f"= {expected_subtotal}, got {self.subtotal_cents}"
            )

        # Critical tax calculation validation using Decimal precision
        expected_tax = int(
            (Decimal(str(self.subtotal_cents)) * self.tax_rate_percent / Decimal("100")).quantize(
                Decimal("1"), rounding="ROUND_HALF_UP"
            )
        )
        tax_difference = abs(self.tax_cents - expected_tax)
        if tax_difference > 1:  # Ultra-strict: maximum 1 cent rounding tolerance
            raise ValueError(
                f"Tax calculation precision error: expected {expected_tax} cents "
                f"({self.tax_rate_percent}% of {self.subtotal_cents}), got {self.tax_cents} cents "
                f"(difference: {tax_difference} cents exceeds 1 cent tolerance)"
            )

        # Critical total validation: total = subtotal + tax
        expected_total = self.subtotal_cents + self.tax_cents
        if self.total_cents != expected_total:
            raise ValueError(
                f"Total calculation error: subtotal ({self.subtotal_cents}) + tax ({self.tax_cents}) "
                f"= {expected_total}, got {self.total_cents}"
            )

        # Business logic validation: detect potential overflow/underflow
        if self.total_cents < self.subtotal_cents:
            raise ValueError(
                f"Invalid calculation: total ({self.total_cents}) less than subtotal ({self.subtotal_cents})"
            )

        # Validate reasonable proportions
        if self.tax_rate_percent > Decimal("0") and self.tax_cents == 0:
            raise ValueError(
                f"Inconsistent data: tax rate {self.tax_rate_percent}% specified but tax amount is 0"
            )

        return self


# Base schemas
class InvoiceBase(BaseModel):
    """Base invoice schema."""

    number: str = Field(..., min_length=1, max_length=50, description="Unique invoice number")
    amount_cents: PositiveInt = Field(..., description="Total invoice amount in cents")
    currency: Currency = Field(default=Currency.TRY, description="Invoice currency")
    due_at: Optional[datetime] = Field(None, description="Payment due date")

    @property
    def amount_decimal(self) -> Decimal:
        """Amount as decimal."""
        return Decimal(self.amount_cents) / Decimal("100")


class PaymentBase(BaseModel):
    """Base payment schema."""

    provider: str = Field(
        ..., min_length=1, max_length=50, description="Payment provider identifier"
    )
    provider_ref: str = Field(
        ..., min_length=1, max_length=255, description="Provider transaction reference"
    )
    amount_cents: PositiveInt = Field(..., description="Payment amount in cents")
    currency: Currency = Field(default=Currency.TRY, description="Payment currency")

    @property
    def amount_decimal(self) -> Decimal:
        """Amount as decimal."""
        return Decimal(self.amount_cents) / Decimal("100")


# Request schemas
class InvoiceCreate(InvoiceBase):
    """Create invoice request."""

    user_id: int = Field(..., description="User ID for the invoice")
    line_items: Optional[List[InvoiceLineItem]] = Field(None, description="Invoice line items")
    meta: Optional[Dict[str, Any]] = Field(None, description="Additional invoice metadata")


class InvoiceUpdate(BaseModel):
    """Update invoice request."""

    status: Optional[InvoiceStatus] = Field(None, description="New invoice status")
    due_at: Optional[datetime] = Field(None, description="New due date")
    meta: Optional[Dict[str, Any]] = Field(None, description="Updated metadata")


class PaymentCreate(PaymentBase):
    """Create payment request with ultra enterprise validation."""

    invoice_id: int = Field(
        ...,
        description="Invoice ID for the payment",
        gt=0,  # Must be positive
    )
    user_id: int = Field(
        ...,
        description="User ID who owns the payment",
        gt=0,  # Must be positive
    )
    meta: Optional[Dict[str, Any]] = Field(None, description="Payment metadata")

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        """ULTRA ENTERPRISE VALIDATION: Validate payment provider."""
        # Known Turkish payment providers
        known_providers = {
            "iyzico",
            "payu",
            "stripe",
            "paypal",
            "masterpass",
            "bkm",
            "garanti",
            "akbank",
            "isbank",
            "yapikredi",
        }

        # Clean and normalize provider name
        provider_clean = v.lower().strip()

        if not provider_clean:
            raise ValueError("Provider name cannot be empty")

        if len(provider_clean) < 2:
            raise ValueError("Provider name too short (minimum 2 characters)")

        # Warning for unknown providers (log but don't fail)
        if provider_clean not in known_providers:
            import logging

            logging.warning(f"Unknown payment provider: {provider_clean}")

        return provider_clean

    @field_validator("provider_ref")
    @classmethod
    def validate_provider_ref(cls, v: str) -> str:
        """ULTRA ENTERPRISE VALIDATION: Validate provider reference."""
        if not v or not v.strip():
            raise ValueError("Provider reference cannot be empty")

        ref_clean = v.strip()

        if len(ref_clean) < 3:
            raise ValueError("Provider reference too short (minimum 3 characters)")

        if len(ref_clean) > 255:
            raise ValueError("Provider reference too long (maximum 255 characters)")

        # Basic format validation (alphanumeric plus common separators)
        import re

        if not re.match(r"^[A-Za-z0-9\-_\.]+$", ref_clean):
            raise ValueError(
                "Provider reference contains invalid characters (only A-Z, 0-9, -, _, . allowed)"
            )

        return ref_clean


class PaymentUpdate(BaseModel):
    """Update payment request."""

    status: Optional[PaymentStatus] = Field(None, description="New payment status")
    paid_at: Optional[datetime] = Field(None, description="Payment completion timestamp")
    meta: Optional[Dict[str, Any]] = Field(None, description="Updated metadata")


# Response schemas
class PaymentResponse(PaymentBase):
    """Payment response schema."""

    id: int = Field(..., description="Payment ID")
    invoice_id: int = Field(..., description="Associated invoice ID")
    status: PaymentStatus = Field(..., description="Payment status")
    paid_at: Optional[datetime] = Field(None, description="Payment completion time")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    meta: Optional[Dict[str, Any]] = Field(None, description="Payment metadata")

    class Config:
        from_attributes = True


class InvoiceResponse(InvoiceBase):
    """Invoice response schema."""

    id: int = Field(..., description="Invoice ID")
    user_id: int = Field(..., description="User ID")
    status: InvoiceStatus = Field(..., description="Invoice status")
    issued_at: Optional[datetime] = Field(None, description="Issue timestamp")
    created_at: datetime = Field(..., description="Creation timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
    meta: Optional[Dict[str, Any]] = Field(None, description="Invoice metadata")

    # Calculated fields
    paid_amount_cents: int = Field(..., description="Total paid amount in cents")
    balance_due_cents: int = Field(..., description="Remaining balance in cents")
    is_overdue: bool = Field(..., description="Whether invoice is overdue")
    is_fully_paid: bool = Field(..., description="Whether invoice is fully paid")

    # Relationships
    payments: List[PaymentResponse] = Field(default_factory=list, description="Associated payments")

    @property
    def paid_amount_decimal(self) -> Decimal:
        """Paid amount as decimal."""
        return Decimal(self.paid_amount_cents) / Decimal("100")

    @property
    def balance_due_decimal(self) -> Decimal:
        """Balance due as decimal."""
        return Decimal(self.balance_due_cents) / Decimal("100")

    class Config:
        from_attributes = True


class InvoiceDetailResponse(InvoiceResponse):
    """Detailed invoice response with line items."""

    line_items: List[InvoiceLineItem] = Field(
        default_factory=list, description="Invoice line items"
    )
    tax_breakdown: TaxCalculation = Field(..., description="Tax breakdown")


# Financial reporting schemas
class FinancialSummary(BaseModel):
    """Financial summary for reporting."""

    total_invoices: int = Field(..., description="Total number of invoices")
    total_amount_cents: int = Field(..., description="Total invoiced amount in cents")
    paid_amount_cents: int = Field(..., description="Total paid amount in cents")
    pending_amount_cents: int = Field(..., description="Total pending amount in cents")
    overdue_amount_cents: int = Field(..., description="Total overdue amount in cents")
    currency: Currency = Field(..., description="Summary currency")

    @property
    def total_amount_decimal(self) -> Decimal:
        """Total amount as decimal."""
        return Decimal(self.total_amount_cents) / Decimal("100")

    @property
    def paid_amount_decimal(self) -> Decimal:
        """Paid amount as decimal."""
        return Decimal(self.paid_amount_cents) / Decimal("100")

    @property
    def pending_amount_decimal(self) -> Decimal:
        """Pending amount as decimal."""
        return Decimal(self.pending_amount_cents) / Decimal("100")

    @property
    def overdue_amount_decimal(self) -> Decimal:
        """Overdue amount as decimal."""
        return Decimal(self.overdue_amount_cents) / Decimal("100")


class PaymentProviderSummary(BaseModel):
    """Payment provider summary."""

    provider: str = Field(..., description="Provider name")
    total_payments: int = Field(..., description="Total number of payments")
    total_amount_cents: int = Field(..., description="Total payment amount in cents")
    successful_payments: int = Field(..., description="Number of successful payments")
    failed_payments: int = Field(..., description="Number of failed payments")

    @property
    def total_amount_decimal(self) -> Decimal:
        """Total amount as decimal."""
        return Decimal(self.total_amount_cents) / Decimal("100")

    @property
    def success_rate(self) -> Decimal:
        """Payment success rate as percentage."""
        if self.total_payments == 0:
            return Decimal("0")
        return Decimal(self.successful_payments * 100) / Decimal(self.total_payments)


# List response schemas
class InvoiceListResponse(BaseModel):
    """Paginated invoice list response."""

    invoices: List[InvoiceResponse] = Field(..., description="List of invoices")
    total: int = Field(..., description="Total number of invoices")
    page: int = Field(..., description="Current page number")
    per_page: int = Field(..., description="Items per page")
    summary: FinancialSummary = Field(..., description="Financial summary")


class PaymentListResponse(BaseModel):
    """Paginated payment list response."""

    payments: List[PaymentResponse] = Field(..., description="List of payments")
    total: int = Field(..., description="Total number of payments")
    page: int = Field(..., description="Current page number")
    per_page: int = Field(..., description="Items per page")
    provider_summary: List[PaymentProviderSummary] = Field(
        default_factory=list, description="Provider summary statistics"
    )
