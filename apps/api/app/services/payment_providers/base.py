"""Base payment provider interface - Task 4.6."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

from ...models.enums import Currency, PaymentStatus


@dataclass
class PaymentIntent:
    """Payment intent data structure."""

    provider_payment_id: str
    client_secret: Optional[str]
    amount_cents: int
    currency: Currency
    status: PaymentStatus
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class PaymentResult:
    """Payment operation result."""

    success: bool
    payment_intent: Optional[PaymentIntent] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class PaymentProvider(ABC):
    """Abstract base class for payment providers - Task 4.6 specification."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize provider with configuration."""
        self.config = config

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name identifier."""
        pass

    @abstractmethod
    async def create_intent(
        self, amount_cents: int, currency: Currency, metadata: Optional[Dict[str, Any]] = None
    ) -> PaymentResult:
        """Create a payment intent.

        Args:
            amount_cents: Payment amount in smallest currency unit (cents)
            currency: Payment currency
            metadata: Additional metadata for the payment

        Returns:
            PaymentResult with payment intent details or error
        """
        pass

    @abstractmethod
    async def retrieve(self, provider_payment_id: str) -> PaymentResult:
        """Retrieve a payment intent by ID.

        Args:
            provider_payment_id: Provider's payment intent ID

        Returns:
            PaymentResult with current payment intent details or error
        """
        pass

    @abstractmethod
    async def confirm(
        self, provider_payment_id: str, params: Optional[Dict[str, Any]] = None
    ) -> PaymentResult:
        """Confirm a payment intent.

        Args:
            provider_payment_id: Provider's payment intent ID
            params: Confirmation parameters (payment method, etc.)

        Returns:
            PaymentResult with confirmation result or error
        """
        pass

    @abstractmethod
    def verify_webhook(self, signature: str, payload: bytes) -> bool:
        """Verify webhook signature.

        Args:
            signature: Webhook signature header
            payload: Raw webhook payload

        Returns:
            True if signature is valid, False otherwise
        """
        pass

    @abstractmethod
    def parse_webhook_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Parse webhook event payload.

        Args:
            payload: Parsed webhook payload

        Returns:
            Standardized event data with keys:
            - event_id: Unique event identifier
            - event_type: Event type (payment_intent.succeeded, etc.)
            - provider_payment_id: Payment intent ID
            - status: New payment status
            - metadata: Additional event metadata
        """
        pass

    def _convert_amount_to_cents(self, amount: Decimal) -> int:
        """Convert decimal amount to cents."""
        return int(amount * 100)

    def _convert_cents_to_amount(self, cents: int) -> Decimal:
        """Convert cents to decimal amount."""
        return Decimal(cents) / Decimal("100")

    def _map_provider_status_to_internal(self, provider_status: str) -> PaymentStatus:
        """Map provider-specific status to internal PaymentStatus enum.

        Should be overridden by concrete providers if needed.
        """
        # Default mapping - override in concrete providers
        status_map = {
            "requires_action": PaymentStatus.REQUIRES_ACTION,
            "requires_payment_method": PaymentStatus.REQUIRES_ACTION,
            "requires_confirmation": PaymentStatus.REQUIRES_ACTION,
            "processing": PaymentStatus.PROCESSING,
            "succeeded": PaymentStatus.SUCCEEDED,
            "failed": PaymentStatus.FAILED,
            "canceled": PaymentStatus.CANCELED,
            "cancelled": PaymentStatus.CANCELED,
            "refunded": PaymentStatus.REFUNDED,
        }

        return status_map.get(provider_status.lower(), PaymentStatus.FAILED)
