"""Stripe payment provider implementation - Task 4.6."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Dict, Optional

import httpx

from ...core.environment import environment
from ...models.enums import Currency, PaymentStatus
from .base import PaymentProvider, PaymentIntent, PaymentResult


class StripeProvider(PaymentProvider):
    """Stripe payment provider implementation."""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("api_key") or environment.STRIPE_SECRET_KEY
        self.webhook_secret = config.get("webhook_secret") or environment.STRIPE_WEBHOOK_SECRET
        self.base_url = "https://api.stripe.com/v1"

    @property
    def provider_name(self) -> str:
        return "stripe"

    async def create_intent(
        self, amount_cents: int, currency: Currency, metadata: Optional[Dict[str, Any]] = None
    ) -> PaymentResult:
        """Create a Stripe payment intent."""
        try:
            payload = {
                "amount": amount_cents,
                "currency": currency.value.lower(),
                "automatic_payment_methods": {"enabled": True},
                "metadata": metadata or {},
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/payment_intents",
                    auth=(self.api_key, ""),
                    data=payload,
                    timeout=30.0,
                )

                response_data = response.json()

                if response.status_code == 200:
                    intent = PaymentIntent(
                        provider_payment_id=response_data["id"],
                        client_secret=response_data["client_secret"],
                        amount_cents=response_data["amount"],
                        currency=Currency(response_data["currency"].upper()),
                        status=self._map_stripe_status_to_internal(response_data["status"]),
                        metadata=response_data.get("metadata"),
                    )

                    return PaymentResult(
                        success=True, payment_intent=intent, raw_response=response_data
                    )
                else:
                    return PaymentResult(
                        success=False,
                        error_message=response_data.get("error", {}).get(
                            "message", "Unknown Stripe error"
                        ),
                        error_code=response_data.get("error", {}).get("code"),
                        raw_response=response_data,
                    )

        except Exception as e:
            return PaymentResult(
                success=False, error_message=f"Stripe API error: {str(e)}", error_code="api_error"
            )

    async def retrieve(self, provider_payment_id: str) -> PaymentResult:
        """Retrieve a Stripe payment intent."""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.base_url}/payment_intents/{provider_payment_id}",
                    auth=(self.api_key, ""),
                    timeout=30.0,
                )

                response_data = response.json()

                if response.status_code == 200:
                    intent = PaymentIntent(
                        provider_payment_id=response_data["id"],
                        client_secret=response_data["client_secret"],
                        amount_cents=response_data["amount"],
                        currency=Currency(response_data["currency"].upper()),
                        status=self._map_stripe_status_to_internal(response_data["status"]),
                        metadata=response_data.get("metadata"),
                    )

                    return PaymentResult(
                        success=True, payment_intent=intent, raw_response=response_data
                    )
                else:
                    return PaymentResult(
                        success=False,
                        error_message=response_data.get("error", {}).get(
                            "message", "Unknown Stripe error"
                        ),
                        error_code=response_data.get("error", {}).get("code"),
                        raw_response=response_data,
                    )

        except Exception as e:
            return PaymentResult(
                success=False, error_message=f"Stripe API error: {str(e)}", error_code="api_error"
            )

    async def confirm(
        self, provider_payment_id: str, params: Optional[Dict[str, Any]] = None
    ) -> PaymentResult:
        """Confirm a Stripe payment intent."""
        try:
            payload = params or {}

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self.base_url}/payment_intents/{provider_payment_id}/confirm",
                    auth=(self.api_key, ""),
                    data=payload,
                    timeout=30.0,
                )

                response_data = response.json()

                if response.status_code == 200:
                    intent = PaymentIntent(
                        provider_payment_id=response_data["id"],
                        client_secret=response_data["client_secret"],
                        amount_cents=response_data["amount"],
                        currency=Currency(response_data["currency"].upper()),
                        status=self._map_stripe_status_to_internal(response_data["status"]),
                        metadata=response_data.get("metadata"),
                    )

                    return PaymentResult(
                        success=True, payment_intent=intent, raw_response=response_data
                    )
                else:
                    return PaymentResult(
                        success=False,
                        error_message=response_data.get("error", {}).get(
                            "message", "Unknown Stripe error"
                        ),
                        error_code=response_data.get("error", {}).get("code"),
                        raw_response=response_data,
                    )

        except Exception as e:
            return PaymentResult(
                success=False, error_message=f"Stripe API error: {str(e)}", error_code="api_error"
            )

    def verify_webhook(self, signature: str, payload: bytes) -> bool:
        """Verify Stripe webhook signature."""
        try:
            # Stripe signature format: t=timestamp,v1=signature,v0=signature (legacy)
            sig_header = signature
            elements = sig_header.split(",")

            timestamp = None
            signatures = []

            for element in elements:
                key, value = element.split("=", 1)
                if key == "t":
                    timestamp = value
                elif key.startswith("v"):
                    signatures.append(value)

            if not timestamp or not signatures:
                return False

            # Create expected signature
            signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
            expected_sig = hmac.new(
                self.webhook_secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256
            ).hexdigest()

            # Compare with any of the provided signatures
            return any(hmac.compare_digest(expected_sig, sig) for sig in signatures)

        except Exception:
            return False

    def parse_webhook_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Stripe webhook event."""
        event_data = payload.get("data", {}).get("object", {})

        return {
            "event_id": payload.get("id"),
            "event_type": payload.get("type"),
            "provider_payment_id": event_data.get("id"),
            "status": self._map_stripe_status_to_internal(event_data.get("status", "")),
            "metadata": {
                "stripe_event": payload,
                "amount": event_data.get("amount"),
                "currency": event_data.get("currency"),
                "created": payload.get("created"),
                "livemode": payload.get("livemode"),
            },
        }

    def _map_stripe_status_to_internal(self, stripe_status: str) -> PaymentStatus:
        """Map Stripe status to internal PaymentStatus."""
        status_map = {
            "requires_payment_method": PaymentStatus.REQUIRES_ACTION,
            "requires_confirmation": PaymentStatus.REQUIRES_ACTION,
            "requires_action": PaymentStatus.REQUIRES_ACTION,
            "processing": PaymentStatus.PROCESSING,
            "requires_capture": PaymentStatus.PROCESSING,
            "succeeded": PaymentStatus.SUCCEEDED,
            "canceled": PaymentStatus.CANCELED,
            "failed": PaymentStatus.FAILED,
        }

        return status_map.get(stripe_status.lower(), PaymentStatus.FAILED)
