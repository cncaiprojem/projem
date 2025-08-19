"""Payment service for Task 4.6 - Payment provider abstraction with webhook handling."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.environment import environment
from ..models.enums import Currency, PaymentStatus, PaidStatus
from ..models.invoice import Invoice
from ..models.payment import Payment, PaymentWebhookEvent, PaymentAuditLog
from .payment_providers import PaymentProviderFactory, PaymentProvider


class PaymentService:
    """Payment service with provider abstraction and webhook handling."""
    
    def __init__(self, db: Session):
        self.db = db
        self.settings = environment
    
    async def create_payment_intent(
        self,
        invoice_id: int,
        provider_name: str = "mock"
    ) -> Tuple[Payment, dict]:
        """Create a payment intent for an invoice.
        
        Args:
            invoice_id: ID of the invoice to create payment for
            provider_name: Payment provider to use
            
        Returns:
            Tuple of (Payment instance, client parameters for frontend)
            
        Raises:
            ValueError: If invoice not found or invalid
            RuntimeError: If payment creation fails
        """
        # Get invoice
        invoice = self.db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            raise ValueError(f"Invoice {invoice_id} not found")
        
        if invoice.paid_status == PaidStatus.PAID:
            raise ValueError(f"Invoice {invoice_id} is already paid")
        
        # Create payment provider
        provider = PaymentProviderFactory.create_provider(provider_name)
        
        # Calculate amount in cents
        amount_cents = int(invoice.total * 100)
        
        # Create payment intent with provider
        result = await provider.create_intent(
            amount_cents=amount_cents,
            currency=Currency.TRY,
            metadata={
                "invoice_id": str(invoice_id),
                "user_id": str(invoice.user_id),
                "license_id": str(invoice.license_id)
            }
        )
        
        if not result.success:
            raise RuntimeError(f"Failed to create payment intent: {result.error_message}")
        
        # Create payment record
        payment = Payment(
            invoice_id=invoice_id,
            provider=provider_name,
            provider_payment_id=result.payment_intent.provider_payment_id,
            amount_cents=amount_cents,
            currency=Currency.TRY,
            status=result.payment_intent.status,
            raw_request={
                "amount_cents": amount_cents,
                "currency": "TRY",
                "metadata": {
                    "invoice_id": str(invoice_id),
                    "user_id": str(invoice.user_id),
                    "license_id": str(invoice.license_id)
                }
            },
            raw_response=result.raw_response
        )
        
        self.db.add(payment)
        self.db.commit()
        self.db.refresh(payment)
        
        # Create audit log
        PaymentAuditLog.log_payment_event(
            self.db,
            payment_id=payment.id,
            invoice_id=invoice_id,
            action="payment_intent_created",
            context={
                "provider": provider_name,
                "amount_cents": amount_cents,
                "provider_payment_id": result.payment_intent.provider_payment_id
            }
        )
        self.db.commit()
        
        # Return client parameters
        client_params = {
            "client_secret": result.payment_intent.client_secret,
            "provider": provider_name,
            "provider_payment_id": result.payment_intent.provider_payment_id,
            "amount_cents": amount_cents,
            "currency": Currency.TRY.value
        }
        
        return payment, client_params
    
    def get_payment_status(self, payment_id: int) -> Optional[Payment]:
        """Get payment by ID."""
        return self.db.query(Payment).filter(Payment.id == payment_id).first()
    
    def get_payment_by_provider_id(self, provider: str, provider_payment_id: str) -> Optional[Payment]:
        """Get payment by provider payment ID."""
        return self.db.query(Payment).filter(
            Payment.provider == provider,
            Payment.provider_payment_id == provider_payment_id
        ).first()
    
    def process_webhook_event(
        self,
        provider: str,
        signature: str,
        payload: bytes,
        parsed_payload: dict
    ) -> dict:
        """Process webhook event with idempotency.
        
        Args:
            provider: Payment provider name
            signature: Webhook signature
            payload: Raw webhook payload
            parsed_payload: Parsed webhook payload
            
        Returns:
            Processing result dictionary
        """
        try:
            # Create payment provider for signature verification
            provider_instance = PaymentProviderFactory.create_provider(provider)
            
            # Verify webhook signature
            if not provider_instance.verify_webhook(signature, payload):
                return {
                    "status": "error",
                    "message": "Invalid webhook signature",
                    "code": "invalid_signature"
                }
            
            # Parse event data
            event_data = provider_instance.parse_webhook_event(parsed_payload)
            
            if not event_data.get("event_id"):
                return {
                    "status": "error",
                    "message": "Missing event ID",
                    "code": "missing_event_id"
                }
            
            # Check for idempotency - has this event been processed?
            existing_event = self.db.query(PaymentWebhookEvent).filter(
                PaymentWebhookEvent.provider == provider,
                PaymentWebhookEvent.event_id == event_data["event_id"]
            ).first()
            
            if existing_event:
                if existing_event.processed:
                    return {
                        "status": "success",
                        "message": "Event already processed (idempotent)",
                        "event_id": event_data["event_id"]
                    }
                else:
                    # Event exists but not processed - continue processing
                    webhook_event = existing_event
            else:
                # Create new webhook event record
                webhook_event = PaymentWebhookEvent(
                    event_id=event_data["event_id"],
                    provider=provider,
                    event_type=event_data["event_type"],
                    raw_event=parsed_payload,
                    processed=False
                )
                self.db.add(webhook_event)
                self.db.flush()  # Get ID but don't commit yet
            
            # Find associated payment
            provider_payment_id = event_data.get("provider_payment_id")
            if not provider_payment_id:
                return {
                    "status": "error",
                    "message": "Missing provider payment ID",
                    "code": "missing_payment_id"
                }
            
            payment = self.get_payment_by_provider_id(provider, provider_payment_id)
            if not payment:
                return {
                    "status": "error",
                    "message": f"Payment not found for provider payment ID: {provider_payment_id}",
                    "code": "payment_not_found"
                }
            
            # Update webhook event with payment association
            webhook_event.payment_id = payment.id
            
            # Process the event based on type
            result = self._process_payment_event(payment, event_data)
            
            # Mark webhook event as processed
            webhook_event.mark_as_processed()
            
            # Commit all changes
            self.db.commit()
            
            return result
            
        except IntegrityError:
            self.db.rollback()
            # Likely a duplicate event_id - return idempotent response
            return {
                "status": "success",
                "message": "Event already processed (idempotent)",
                "event_id": event_data.get("event_id", "unknown")
            }
        except Exception as e:
            self.db.rollback()
            return {
                "status": "error",
                "message": f"Webhook processing failed: {str(e)}",
                "code": "processing_error"
            }
    
    def _process_payment_event(self, payment: Payment, event_data: dict) -> dict:
        """Process a specific payment event."""
        event_type = event_data.get("event_type", "")
        new_status = event_data.get("status")
        
        # Update payment status
        old_status = payment.status
        if new_status and new_status != old_status:
            payment.status = new_status
            
            # Update raw_response with webhook data
            if payment.raw_response is None:
                payment.raw_response = {}
            payment.raw_response[f"webhook_{event_type}"] = event_data.get("metadata", {})
        
        # Get associated invoice
        invoice = self.db.query(Invoice).filter(Invoice.id == payment.invoice_id).first()
        if not invoice:
            return {
                "status": "error",
                "message": f"Associated invoice {payment.invoice_id} not found",
                "code": "invoice_not_found"
            }
        
        # Process based on event type and status
        if new_status == PaymentStatus.SUCCEEDED:
            # Payment succeeded - mark invoice as paid
            invoice.paid_status = PaidStatus.PAID
            
            # Create audit log
            PaymentAuditLog.log_payment_event(
                self.db,
                payment_id=payment.id,
                invoice_id=invoice.id,
                action="payment_succeeded",
                actor_type="webhook",
                actor_id=event_data.get("event_id"),
                context={
                    "event_type": event_type,
                    "old_status": old_status.value if old_status else None,
                    "new_status": new_status.value,
                    "provider": payment.provider
                }
            )
            
            return {
                "status": "success",
                "message": "Payment succeeded, invoice marked as paid",
                "event_id": event_data.get("event_id"),
                "action": "payment_succeeded"
            }
            
        elif new_status == PaymentStatus.FAILED:
            # Payment failed - mark invoice as failed
            invoice.paid_status = PaidStatus.FAILED
            
            # Create audit log
            PaymentAuditLog.log_payment_event(
                self.db,
                payment_id=payment.id,
                invoice_id=invoice.id,
                action="payment_failed",
                actor_type="webhook",
                actor_id=event_data.get("event_id"),
                context={
                    "event_type": event_type,
                    "old_status": old_status.value if old_status else None,
                    "new_status": new_status.value,
                    "provider": payment.provider,
                    "failure_reason": event_data.get("metadata", {}).get("failure_reason")
                }
            )
            
            return {
                "status": "success",
                "message": "Payment failed, invoice marked as failed",
                "event_id": event_data.get("event_id"),
                "action": "payment_failed"
            }
            
        elif new_status == PaymentStatus.REFUNDED:
            # Payment refunded - mark invoice as refunded
            invoice.paid_status = PaidStatus.REFUNDED
            
            # Create audit log
            PaymentAuditLog.log_payment_event(
                self.db,
                payment_id=payment.id,
                invoice_id=invoice.id,
                action="payment_refunded",
                actor_type="webhook",
                actor_id=event_data.get("event_id"),
                context={
                    "event_type": event_type,
                    "old_status": old_status.value if old_status else None,
                    "new_status": new_status.value,
                    "provider": payment.provider
                }
            )
            
            return {
                "status": "success",
                "message": "Payment refunded, invoice marked as refunded",
                "event_id": event_data.get("event_id"),
                "action": "payment_refunded"
            }
        
        else:
            # Status update only - log the change
            PaymentAuditLog.log_payment_event(
                self.db,
                payment_id=payment.id,
                invoice_id=invoice.id,
                action="payment_status_updated",
                actor_type="webhook",
                actor_id=event_data.get("event_id"),
                context={
                    "event_type": event_type,
                    "old_status": old_status.value if old_status else None,
                    "new_status": new_status.value if new_status else None,
                    "provider": payment.provider
                }
            )
            
            return {
                "status": "success",
                "message": "Payment status updated",
                "event_id": event_data.get("event_id"),
                "action": "status_updated"
            }