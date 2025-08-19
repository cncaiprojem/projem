"""Mock payment provider for testing - Task 4.6."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from ...models.enums import Currency, PaymentStatus
from .base import PaymentProvider, PaymentIntent, PaymentResult


class MockProvider(PaymentProvider):
    """Mock payment provider for testing and development."""
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.test_mode = config.get("test_mode", True)
        self.fail_percentage = config.get("fail_percentage", 0.0)  # 0-1.0
        
    @property
    def provider_name(self) -> str:
        return "mock"
    
    async def create_intent(
        self,
        amount_cents: int,
        currency: Currency,
        metadata: Optional[Dict[str, Any]] = None
    ) -> PaymentResult:
        """Create a mock payment intent."""
        try:
            # Generate mock payment intent ID
            provider_payment_id = f"pi_mock_{uuid.uuid4().hex[:24]}"
            client_secret = f"{provider_payment_id}_secret_{uuid.uuid4().hex[:12]}"
            
            # Simulate failure based on configuration
            import random
            if random.random() < self.fail_percentage:
                return PaymentResult(
                    success=False,
                    error_message="Mock payment failure for testing",
                    error_code="mock_failure",
                    raw_response={
                        "error": "mock_failure",
                        "amount": amount_cents,
                        "currency": currency.value
                    }
                )
            
            intent = PaymentIntent(
                provider_payment_id=provider_payment_id,
                client_secret=client_secret,
                amount_cents=amount_cents,
                currency=currency,
                status=PaymentStatus.REQUIRES_ACTION,
                metadata=metadata
            )
            
            return PaymentResult(
                success=True,
                payment_intent=intent,
                raw_response={
                    "id": provider_payment_id,
                    "client_secret": client_secret,
                    "amount": amount_cents,
                    "currency": currency.value.lower(),
                    "status": "requires_action",
                    "metadata": metadata or {},
                    "test_mode": self.test_mode
                }
            )
            
        except Exception as e:
            return PaymentResult(
                success=False,
                error_message=f"Mock provider error: {str(e)}",
                error_code="mock_error"
            )
    
    async def retrieve(self, provider_payment_id: str) -> PaymentResult:
        """Retrieve a mock payment intent."""
        try:
            # Simulate different statuses based on payment ID patterns
            if "_failed_" in provider_payment_id:
                status = PaymentStatus.FAILED
                mock_status = "failed"
            elif "_succeeded_" in provider_payment_id:
                status = PaymentStatus.SUCCEEDED
                mock_status = "succeeded"
            elif "_processing_" in provider_payment_id:
                status = PaymentStatus.PROCESSING
                mock_status = "processing"
            else:
                status = PaymentStatus.REQUIRES_ACTION
                mock_status = "requires_action"
            
            intent = PaymentIntent(
                provider_payment_id=provider_payment_id,
                client_secret=f"{provider_payment_id}_secret",
                amount_cents=10000,  # Mock amount
                currency=Currency.TRY,
                status=status,
                metadata={"mock": True}
            )
            
            return PaymentResult(
                success=True,
                payment_intent=intent,
                raw_response={
                    "id": provider_payment_id,
                    "client_secret": f"{provider_payment_id}_secret",
                    "amount": 10000,
                    "currency": "try",
                    "status": mock_status,
                    "metadata": {"mock": True},
                    "test_mode": self.test_mode
                }
            )
            
        except Exception as e:
            return PaymentResult(
                success=False,
                error_message=f"Mock provider error: {str(e)}",
                error_code="mock_error"
            )
    
    async def confirm(
        self,
        provider_payment_id: str,
        params: Optional[Dict[str, Any]] = None
    ) -> PaymentResult:
        """Confirm a mock payment intent."""
        try:
            # Simulate confirmation based on payment ID or parameters
            if params and params.get("simulate_failure"):
                status = PaymentStatus.FAILED
                mock_status = "failed"
            elif params and params.get("simulate_processing"):
                status = PaymentStatus.PROCESSING
                mock_status = "processing"
            else:
                status = PaymentStatus.SUCCEEDED
                mock_status = "succeeded"
            
            intent = PaymentIntent(
                provider_payment_id=provider_payment_id,
                client_secret=f"{provider_payment_id}_secret",
                amount_cents=10000,  # Mock amount
                currency=Currency.TRY,
                status=status,
                metadata={"mock": True, "confirmed": True}
            )
            
            return PaymentResult(
                success=True,
                payment_intent=intent,
                raw_response={
                    "id": provider_payment_id,
                    "client_secret": f"{provider_payment_id}_secret",
                    "amount": 10000,
                    "currency": "try",
                    "status": mock_status,
                    "metadata": {"mock": True, "confirmed": True},
                    "test_mode": self.test_mode,
                    "confirmation_method": params.get("payment_method") if params else "mock_method"
                }
            )
            
        except Exception as e:
            return PaymentResult(
                success=False,
                error_message=f"Mock provider error: {str(e)}",
                error_code="mock_error"
            )
    
    def verify_webhook(self, signature: str, payload: bytes) -> bool:
        """Verify mock webhook signature - always returns True for testing."""
        # In test mode, always accept webhooks
        if self.test_mode:
            return True
        
        # For stricter testing, implement actual verification
        return signature == "mock_signature"
    
    def parse_webhook_event(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Parse mock webhook event."""
        # Mock webhook event structure
        event_data = payload.get("data", {}).get("object", payload)
        
        return {
            "event_id": payload.get("id", f"evt_mock_{uuid.uuid4().hex[:16]}"),
            "event_type": payload.get("type", "payment_intent.succeeded"),
            "provider_payment_id": event_data.get("id", event_data.get("payment_intent_id")),
            "status": self._map_mock_status_to_internal(event_data.get("status", "succeeded")),
            "metadata": {
                "mock_event": True,
                "test_mode": self.test_mode,
                "original_payload": payload,
                "amount": event_data.get("amount"),
                "currency": event_data.get("currency")
            }
        }
    
    def _map_mock_status_to_internal(self, mock_status: str) -> PaymentStatus:
        """Map mock status to internal PaymentStatus."""
        return self._map_provider_status_to_internal(mock_status)