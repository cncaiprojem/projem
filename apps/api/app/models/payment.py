"""Payment model for Task 4.6 - Payment provider abstraction with webhook handling."""

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


class Payment(Base, TimestampMixin):
    """Payment transactions with provider abstraction - Task 4.6 specification.
    
    ULTRA-ENTERPRISE DESIGN PRINCIPLES:
    - Banking-grade precision using amount_cents (BigInteger)
    - Provider-agnostic interface with unique provider_payment_id tracking
    - Raw request/response logging for audit compliance
    - Webhook idempotency support via webhook events table
    - Turkish KVKK compliance with encrypted sensitive data
    - Multi-provider support (Stripe, local PSP, etc.)
    """
    
    __tablename__ = "payments"
    
    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    
    # Foreign key - Task 4.6 specification
    invoice_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("invoices.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
        comment="Invoice this payment is for"
    )
    
    # Provider integration - Task 4.6 specification
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Payment provider identifier (stripe, iyzico, etc.)"
    )
    
    provider_payment_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Provider payment intent ID"
    )
    
    # Financial details with cent precision - Task 4.6 specification
    amount_cents: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="Payment amount in smallest currency unit (cents)"
    )
    
    currency: Mapped[Currency] = mapped_column(
        SQLEnum(Currency, name="currency_enum"),
        nullable=False,
        server_default=text("'TRY'"),
        comment="Payment currency"
    )
    
    # Status tracking - Task 4.6 specification
    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus, name="payment_status_enum"),
        nullable=False,
        server_default=text("'requires_action'"),
        index=True,
        comment="Payment status"
    )
    
    # Provider request/response logging - Task 4.6 specification
    raw_request: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Raw provider request data"
    )
    
    raw_response: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Raw provider response data"
    )
    
    # Relationships
    invoice: Mapped[Invoice] = relationship(
        "Invoice",
        back_populates="payments",
        lazy="select"
    )
    
    # Enterprise constraints and indexes
    __table_args__ = (
        # Task 4.6: Provider payment ID uniqueness per provider
        UniqueConstraint(
            "provider", "provider_payment_id",
            name="uq_payments_provider_payment_id"
        ),
        
        # Financial integrity constraints
        CheckConstraint(
            "amount_cents > 0",
            name="ck_payments_amount_positive"
        ),
        
        # Currency constraint
        CheckConstraint(
            "currency = 'TRY'",
            name="ck_payments_currency_try_only"
        ),
        
        # Optimized indexes for payment queries
        Index(
            "idx_payments_invoice_status",
            "invoice_id", "status"
        ),
        Index(
            "idx_payments_provider_status",
            "provider", "status"
        ),
        Index(
            "idx_payments_created_at",
            "created_at"
        ),
        
        # Partial index for active payments
        Index(
            "idx_payments_active",
            "provider", "status", "created_at",
            postgresql_where=text("status IN ('requires_action', 'processing')")
        ),
    )
    
    def __repr__(self) -> str:
        return f"<Payment(id={self.id}, provider_payment_id='{self.provider_payment_id}', amount_cents={self.amount_cents})>"
    
    def __str__(self) -> str:
        return f"Payment {self.provider_payment_id}: {self.amount_decimal:.2f} {self.currency.value}"
    
    @property
    def amount_decimal(self) -> Decimal:
        """Convert cents to decimal amount for display with precision."""
        return Decimal(self.amount_cents) / Decimal('100')
    
    @property
    def is_successful(self) -> bool:
        """Check if payment was successful."""
        return self.status == PaymentStatus.SUCCEEDED
    
    @property
    def is_pending(self) -> bool:
        """Check if payment is still pending."""
        return self.status in [PaymentStatus.REQUIRES_ACTION, PaymentStatus.PROCESSING]
    
    @property
    def is_failed(self) -> bool:
        """Check if payment failed."""
        return self.status in [PaymentStatus.FAILED, PaymentStatus.CANCELED]
    
    def mark_as_succeeded(self) -> None:
        """Mark payment as successfully completed."""
        self.status = PaymentStatus.SUCCEEDED
    
    def mark_as_failed(self, reason: str) -> None:
        """Mark payment as failed with reason."""
        self.status = PaymentStatus.FAILED
        
        # Store failure details in raw_response if not already set
        if self.raw_response is None:
            self.raw_response = {}
        self.raw_response['failure_reason'] = reason
        self.raw_response['failed_at'] = datetime.now(timezone.utc).isoformat()
    
    def mark_as_canceled(self) -> None:
        """Mark payment as canceled."""
        self.status = PaymentStatus.CANCELED


class PaymentWebhookEvent(Base, TimestampMixin):
    """Webhook events for payment idempotency - Task 4.6 specification."""
    
    __tablename__ = "payment_webhook_events"
    
    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    
    # Event identification
    event_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        comment="Unique provider event ID for idempotency"
    )
    
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Payment provider identifier"
    )
    
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Event type (payment_intent.succeeded, etc.)"
    )
    
    # Associated payment
    payment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        comment="Associated payment ID"
    )
    
    # Processing status
    processed: Mapped[bool] = mapped_column(
        nullable=False,
        server_default=text('false'),
        comment="Whether event was processed"
    )
    
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When event was processed"
    )
    
    # Raw event data
    raw_event: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment="Raw webhook event data"
    )
    
    # Relationships
    payment: Mapped[Optional[Payment]] = relationship(
        "Payment",
        lazy="select"
    )
    
    # Enterprise constraints and indexes
    __table_args__ = (
        # Idempotency constraint - unique event_id per provider
        UniqueConstraint(
            "provider", "event_id",
            name="uq_webhook_events_provider_event_id"
        ),
        
        # Performance indexes
        Index(
            "idx_webhook_events_provider_processed",
            "provider", "processed"
        ),
        Index(
            "idx_webhook_events_created_at",
            "created_at"
        ),
    )
    
    def __repr__(self) -> str:
        return f"<PaymentWebhookEvent(id={self.id}, event_id='{self.event_id}', processed={self.processed})>"
    
    def mark_as_processed(self) -> None:
        """Mark event as processed."""
        self.processed = True
        self.processed_at = datetime.now(timezone.utc)


class PaymentAuditLog(Base):
    """Payment audit logs for compliance - Task 4.6 specification."""
    
    __tablename__ = "payment_audit_logs"
    
    # Primary key
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    
    # Associated payment
    payment_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        comment="Associated payment ID"
    )
    
    invoice_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("invoices.id", ondelete="SET NULL"),
        nullable=True,
        comment="Associated invoice ID"
    )
    
    # Audit details
    action: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Action performed (payment_succeeded, payment_failed, etc.)"
    )
    
    actor_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Who performed action (system, webhook, user)"
    )
    
    actor_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="Actor identifier"
    )
    
    # Event context
    context: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional context and metadata"
    )
    
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),  # IPv6 max length
        nullable=True,
        comment="IP address of request"
    )
    
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(1000),
        nullable=True,
        comment="User agent string"
    )
    
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text('now()'),
        nullable=False
    )
    
    # Relationships
    payment: Mapped[Optional[Payment]] = relationship(
        "Payment",
        lazy="select"
    )
    
    # Enterprise constraints and indexes
    __table_args__ = (
        # Performance indexes
        Index(
            "idx_audit_logs_payment_action",
            "payment_id", "action"
        ),
        Index(
            "idx_audit_logs_created_at",
            "created_at"
        ),
    )
    
    def __repr__(self) -> str:
        return f"<PaymentAuditLog(id={self.id}, action='{self.action}', actor_type='{self.actor_type}')>"
    
    @classmethod
    def log_payment_event(
        cls,
        db_session,
        payment_id: Optional[int],
        invoice_id: Optional[int],
        action: str,
        actor_type: str = "system",
        actor_id: Optional[str] = None,
        context: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> PaymentAuditLog:
        """Create a new audit log entry."""
        audit_log = cls(
            payment_id=payment_id,
            invoice_id=invoice_id,
            action=action,
            actor_type=actor_type,
            actor_id=actor_id,
            context=context,
            ip_address=ip_address,
            user_agent=user_agent
        )
        db_session.add(audit_log)
        return audit_log