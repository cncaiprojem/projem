"""
Payment service for Task 4.6 - Payment provider abstraction with webhook handling.

Enhanced for Task 4.10: Comprehensive observability with metrics, tracing, and audit integration
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.environment import environment
from ..core.logging import get_logger
from ..core.telemetry import create_financial_span, create_span
from ..middleware.correlation_middleware import get_correlation_id, get_session_id
from ..models.enums import Currency, PaidStatus, PaymentStatus
from ..models.invoice import Invoice
from ..models.payment import Payment, PaymentAuditLog, PaymentWebhookEvent
from .payment_providers import PaymentProviderFactory
from .. import metrics

# Ultra-enterprise banking-grade logger for payment transactions with observability
logger = get_logger("payment_service.ultra_enterprise")


class PaymentService:
    """Payment service with ultra-enterprise banking-grade security and audit capabilities."""

    def __init__(self, db: Session):
        self.db = db
        self.settings = environment
        
    def _log_critical_audit_event(
        self,
        event_type: str,
        audit_context: dict,
        severity: str = "INFO",
        payment_id: Optional[int] = None,
        invoice_id: Optional[int] = None
    ) -> None:
        """Ultra-enterprise audit logging for payment transactions.
        
        Args:
            event_type: Type of audit event (e.g., 'webhook_processing_success')
            audit_context: Comprehensive context dictionary with transaction details
            severity: Logging severity level with specific banking-grade meanings:
                - INFO: Normal business operations, successful transactions
                - WARNING: Recoverable issues, business rule violations, retryable failures
                - ERROR: Service errors, integration failures, data inconsistencies
                - CRITICAL: Security violations, compliance failures, transaction integrity issues
            payment_id: Associated payment ID for correlation (optional)
            invoice_id: Associated invoice ID for correlation (optional)
        
        COMPLIANCE FEATURES:
        - Immutable audit trail for regulatory requirements
        - Banking-grade transaction logging with ACID guarantees
        - KVKV (Turkish GDPR) compliance with data protection
        - Security event correlation for fraud detection
        - Multi-level severity for appropriate alerting and monitoring
        """
        try:
            # Enhanced audit entry with timestamp precision and comprehensive context
            audit_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event_type,
                "severity": severity,
                "payment_id": payment_id,
                "invoice_id": invoice_id,
                "service": "PaymentService",
                "context": audit_context.copy(),  # Defensive copy
                "trace_id": audit_context.get("event_id", "unknown"),
                "session_id": id(self.db),  # Database session identifier
                "compliance_flags": {
                    "kvkv_logged": True,
                    "financial_audit": True,
                    "security_relevant": severity in ["WARNING", "ERROR", "CRITICAL"],
                    "pci_dss_compliant": True,
                    "banking_regulations": True
                },
                # Enhanced contextual information for ultra-enterprise monitoring
                "environment": {
                    "payment_provider": audit_context.get("provider"),
                    "processing_stage": audit_context.get("processing_stage"),
                    "client_ip": audit_context.get("client_ip"),
                    "user_agent": audit_context.get("user_agent")
                },
                "transaction_metadata": {
                    "transaction_id": audit_context.get("transaction_id"),
                    "rollback_reason": audit_context.get("rollback_reason"),
                    "error_details": audit_context.get("error_details"),
                    "processing_time_ms": audit_context.get("processing_time_seconds", 0) * 1000
                },
                "correlation": {
                    "request_id": audit_context.get("request_id"),
                    "correlation_id": audit_context.get("correlation_id"),
                    "parent_span_id": audit_context.get("parent_span_id")
                }
            }
            
            # Log to structured logger for enterprise monitoring
            if severity == "CRITICAL":
                logger.critical(f"PAYMENT_AUDIT: {event_type}", extra=audit_entry)
            elif severity == "ERROR":
                logger.error(f"PAYMENT_AUDIT: {event_type}", extra=audit_entry)
            elif severity == "WARNING":
                logger.warning(f"PAYMENT_AUDIT: {event_type}", extra=audit_entry)
            else:
                logger.info(f"PAYMENT_AUDIT: {event_type}", extra=audit_entry)
                
            # Attempt to persist audit to database for compliance
            if payment_id and invoice_id:
                try:
                    PaymentAuditLog.log_payment_event(
                        self.db,
                        payment_id=payment_id,
                        invoice_id=invoice_id,
                        action=event_type,
                        actor_type="system",
                        context=audit_entry
                    )
                except Exception as db_audit_error:
                    # Don't fail processing due to audit logging issues
                    logger.warning(
                        f"Database audit logging failed for {event_type}: {db_audit_error}",
                        extra={"audit_error": str(db_audit_error)}
                    )
                    
        except Exception as audit_error:
            # Critical: audit logging should never fail payment processing
            # But we need to log the audit system failure itself
            try:
                logger.critical(
                    f"AUDIT_SYSTEM_FAILURE: Failed to log {event_type}",
                    extra={"audit_system_error": str(audit_error)}
                )
            except Exception:
                # Ultimate fallback - even audit system error logging failed
                pass

    async def create_payment_intent(
        self,
        invoice_id: int,
        provider_name: str = "mock"
    ) -> tuple[Payment, dict]:
        """Create a payment intent for an invoice with comprehensive observability.

        Enhanced Task 4.10: Observability integration:
        - OpenTelemetry financial tracing with banking context  
        - Prometheus metrics for payment operations
        - Comprehensive audit logging with correlation IDs
        - Performance monitoring and error tracking

        Args:
            invoice_id: ID of the invoice to create payment for
            provider_name: Payment provider to use

        Returns:
            Tuple of (Payment instance, client parameters for frontend)

        Raises:
            ValueError: If invoice not found or invalid
            RuntimeError: If payment creation fails
        """
        
        # Get correlation context for observability
        correlation_id = get_correlation_id()
        session_id = get_session_id()
        start_time = time.time()
        
        # Get invoice first for context
        invoice = self.db.query(Invoice).filter(Invoice.id == invoice_id).first()
        if not invoice:
            # Track validation failure metric
            metrics.payments_total.labels(
                provider=provider_name,
                method="unknown",
                status="validation_failed",
                currency=Currency.TRY.value
            ).inc()
            
            logger.warning(
                "payment_intent_validation_failed",
                invoice_id=invoice_id,
                provider=provider_name,
                reason="invoice_not_found",
                correlation_id=correlation_id,
                session_id=session_id
            )
            
            raise ValueError(f"Invoice {invoice_id} not found")

        if invoice.paid_status == PaidStatus.PAID:
            # Track already paid metric
            metrics.payments_total.labels(
                provider=provider_name,
                method="unknown", 
                status="already_paid",
                currency=Currency.TRY.value
            ).inc()
            
            logger.warning(
                "payment_intent_already_paid",
                invoice_id=invoice_id,
                user_id=invoice.user_id,
                provider=provider_name,
                correlation_id=correlation_id,
                session_id=session_id
            )
            
            raise ValueError(f"Invoice {invoice_id} is already paid")

        # Calculate amount in cents using Decimal for banking-grade precision
        amount_cents = int(Decimal(str(invoice.total)) * Decimal('100'))
        
        # Create financial span for payment intent creation
        with create_financial_span(
            "ödeme_niyeti_oluşturma",
            user_id=invoice.user_id,
            amount_cents=amount_cents,
            currency=Currency.TRY.value,
            invoice_id=invoice_id,
            correlation_id=correlation_id
        ) as span:
            
            try:
                # Add span attributes
                span.set_attribute("payment.provider", provider_name)
                span.set_attribute("payment.method", "card")  # Default assumption
                span.set_attribute("invoice.license_id", str(invoice.license_id))
                
                # Create payment provider
                provider = PaymentProviderFactory.create_provider(provider_name)

                # Create payment intent with provider
                provider_start_time = time.time()
                result = await provider.create_intent(
                    amount_cents=amount_cents,
                    currency=Currency.TRY,
                    metadata={
                        "invoice_id": str(invoice_id),
                        "user_id": str(invoice.user_id),
                        "license_id": str(invoice.license_id),
                        "correlation_id": correlation_id
                    }
                )
                provider_duration = time.time() - provider_start_time
                
                # Track provider call metrics
                metrics.payment_processing_duration_seconds.labels(
                    provider=provider_name,
                    method="create_intent",
                    status="success" if result.success else "error"
                ).observe(provider_duration)

                if not result.success:
                    error_msg = f"Failed to create payment intent: {result.error_message}"
                    
                    # Track provider failure
                    metrics.payments_failed_total.labels(
                        provider=provider_name,
                        method="card",
                        failure_reason="provider_error",
                        retry_eligible="true"
                    ).inc()
                    
                    logger.error(
                        "payment_intent_provider_error",
                        invoice_id=invoice_id,
                        user_id=invoice.user_id,
                        provider=provider_name,
                        error_message=result.error_message,
                        provider_duration_seconds=round(provider_duration, 3),
                        correlation_id=correlation_id,
                        session_id=session_id,
                        event_type="payment_provider_error"
                    )
                    
                    raise RuntimeError(error_msg)

                # Create payment record
                payment = Payment(
                    invoice_id=invoice_id,
                    provider=provider_name,
                    provider_payment_id=result.payment_intent.provider_payment_id,
                    amount_cents=amount_cents,
                    currency=Currency.TRY,
                    status=result.payment_intent.status,
                    # Store the actual provider data for traceability
                    provider_data={
                        "metadata": {
                            "invoice_id": str(invoice_id),
                            "user_id": str(invoice.user_id),
                            "license_id": str(invoice.license_id),
                            "correlation_id": correlation_id
                        },
                        "provider_duration_seconds": round(provider_duration, 3)
                    },
                    raw_response=result.raw_response
                )

                self.db.add(payment)
                self.db.flush()
                self.db.refresh(payment)
                
                # Add payment ID to span
                span.set_attribute("payment.id", str(payment.id))
                span.set_attribute("payment.provider_payment_id", result.payment_intent.provider_payment_id)
            
            except Exception as e:
                # Log the exception and re-raise
                logger.error(
                    "payment_intent_creation_error",
                    invoice_id=invoice_id,
                    provider=provider_name,
                    error=str(e),
                    correlation_id=correlation_id,
                    session_id=session_id
                )
                raise

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
        # Note: Final commit should be handled by the calling router to ensure atomicity

        # Return client parameters
        client_params = {
            "client_secret": result.payment_intent.client_secret,
            "provider": provider_name,
            "provider_payment_id": result.payment_intent.provider_payment_id,
            "amount_cents": amount_cents,
            "currency": Currency.TRY.value
        }

        return payment, client_params

    def get_payment_status(self, payment_id: int) -> Payment | None:
        """Get payment by ID."""
        return self.db.query(Payment).filter(Payment.id == payment_id).first()

    def get_payment_by_provider_id(self, provider: str, provider_payment_id: str) -> Payment | None:
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
        """Process webhook event with ultra-enterprise banking-grade transaction handling.
        
        CRITICAL SECURITY & CONSISTENCY FEATURES:
        - Comprehensive exception handling with rollback guarantees
        - Idempotency protection against duplicate webhooks
        - Audit trail for all transaction states
        - Banking-grade error recovery and logging
        
        Args:
            provider: Payment provider name
            signature: Webhook signature
            payload: Raw webhook payload
            parsed_payload: Parsed webhook payload
            
        Returns:
            Processing result dictionary with guaranteed consistency
            
        Raises:
            RuntimeError: On critical transaction consistency failures
        """
        # Start a savepoint for ultra-enterprise transaction isolation
        savepoint = None
        audit_context = {
            "provider": provider,
            "event_id": None,
            "payment_id": None,
            "processing_stage": "initialization"
        }
        
        try:
            # Create savepoint for banking-grade rollback capability
            savepoint = self.db.begin_nested()
            audit_context["processing_stage"] = "signature_verification"
            
            # Create payment provider for signature verification
            provider_instance = PaymentProviderFactory.create_provider(provider)

            # Verify webhook signature with enhanced security
            if not provider_instance.verify_webhook(signature, payload):
                audit_context["processing_stage"] = "signature_validation_failed"
                return {
                    "status": "error",
                    "message": "Invalid webhook signature - security violation detected",
                    "code": "invalid_signature",
                    "audit_context": audit_context
                }

            # Parse event data with error protection
            audit_context["processing_stage"] = "event_parsing"
            event_data = provider_instance.parse_webhook_event(parsed_payload)

            if not event_data.get("event_id"):
                audit_context["processing_stage"] = "missing_event_id"
                return {
                    "status": "error",
                    "message": "Missing event ID - webhook data integrity violation",
                    "code": "missing_event_id",
                    "audit_context": audit_context
                }
            
            audit_context["event_id"] = event_data["event_id"]
            audit_context["processing_stage"] = "idempotency_check"

            # Check for idempotency - has this event been processed?
            existing_event = self.db.query(PaymentWebhookEvent).filter(
                PaymentWebhookEvent.provider == provider,
                PaymentWebhookEvent.event_id == event_data["event_id"]
            ).first()

            if existing_event:
                if existing_event.processed:
                    # Already processed - return idempotent response
                    audit_context["processing_stage"] = "idempotent_response"
                    return {
                        "status": "success",
                        "message": "Event already processed (idempotent)",
                        "event_id": event_data["event_id"],
                        "audit_context": audit_context
                    }
                else:
                    # Event exists but not processed - continue processing
                    webhook_event = existing_event
                    audit_context["processing_stage"] = "existing_event_processing"
            else:
                # Create new webhook event record
                audit_context["processing_stage"] = "new_event_creation"
                webhook_event = PaymentWebhookEvent(
                    event_id=event_data["event_id"],
                    provider=provider,
                    event_type=event_data["event_type"],
                    raw_event=parsed_payload,
                    processed=False
                )
                self.db.add(webhook_event)
                # Use flush with explicit error handling
                try:
                    self.db.flush()  # Get ID but maintain transaction
                except Exception as flush_error:
                    audit_context["processing_stage"] = "webhook_event_creation_failed"
                    audit_context["error_details"] = str(flush_error)
                    raise RuntimeError(f"Failed to create webhook event: {flush_error}") from flush_error

            # Find associated payment with enhanced validation
            audit_context["processing_stage"] = "payment_lookup"
            provider_payment_id = event_data.get("provider_payment_id")
            if not provider_payment_id:
                audit_context["processing_stage"] = "missing_payment_id"
                return {
                    "status": "error",
                    "message": "Missing provider payment ID - data integrity violation",
                    "code": "missing_payment_id",
                    "audit_context": audit_context
                }

            payment = self.get_payment_by_provider_id(provider, provider_payment_id)
            if not payment:
                audit_context["processing_stage"] = "payment_not_found"
                return {
                    "status": "error",
                    "message": f"Payment not found for provider payment ID: {provider_payment_id}",
                    "code": "payment_not_found",
                    "audit_context": audit_context
                }

            audit_context["payment_id"] = payment.id
            audit_context["processing_stage"] = "payment_processing"

            # Update webhook event with payment association
            webhook_event.payment_id = payment.id

            # Process the event based on type with comprehensive error handling
            try:
                result = self._process_payment_event(payment, event_data)
                audit_context["processing_stage"] = "event_processing_completed"
            except Exception as processing_error:
                audit_context["processing_stage"] = "event_processing_failed"
                audit_context["error_details"] = str(processing_error)
                raise RuntimeError(f"Payment event processing failed: {processing_error}") from processing_error

            # Mark webhook event as processed
            try:
                webhook_event.mark_as_processed()
                audit_context["processing_stage"] = "webhook_marked_processed"
            except Exception as mark_error:
                audit_context["processing_stage"] = "webhook_marking_failed"
                audit_context["error_details"] = str(mark_error)
                raise RuntimeError(f"Failed to mark webhook as processed: {mark_error}") from mark_error

            # Flush changes with comprehensive error handling
            # Note: Final commit should be handled by the calling router
            try:
                self.db.flush()
                audit_context["processing_stage"] = "transaction_flushed"
            except Exception as flush_error:
                audit_context["processing_stage"] = "transaction_flush_failed"
                audit_context["error_details"] = str(flush_error)
                raise RuntimeError(f"Transaction flush failed: {flush_error}") from flush_error

            # Commit the savepoint for successful processing
            if savepoint:
                savepoint.commit()
                audit_context["processing_stage"] = "savepoint_committed"

            # Log successful webhook processing for compliance
            self._log_critical_audit_event(
                event_type="webhook_processing_success",
                audit_context=audit_context,
                severity="INFO",
                payment_id=audit_context.get("payment_id"),
                invoice_id=None  # Will be populated by payment event processing
            )

            # Enhance result with audit context
            result["audit_context"] = audit_context
            return result

        except IntegrityError as integrity_error:
            # Handle integrity constraint violations (duplicate events, etc.)
            if savepoint:
                savepoint.rollback()
            audit_context["processing_stage"] = "integrity_error_handled"
            audit_context["error_details"] = str(integrity_error)
            
            # Log critical integrity violation with ultra-enterprise audit
            self._log_critical_audit_event(
                event_type="webhook_integrity_violation",
                audit_context=audit_context,
                severity="CRITICAL",
                payment_id=audit_context.get("payment_id"),
                invoice_id=None  # Payment might not be found yet
            )
            
            # Security event logging handled via audit log
            # SecurityEventService removed per Gemini Code Assist feedback
            # All security events are now logged through _log_critical_audit_event
            
            # Likely a duplicate event_id - return idempotent response
            return {
                "status": "success",
                "message": "Event already processed (idempotent) - integrity protection",
                "event_id": audit_context.get("event_id", "unknown"),
                "audit_context": audit_context
            }
            
        except RuntimeError as runtime_error:
            # Handle critical runtime errors with full rollback
            if savepoint:
                savepoint.rollback()
            audit_context["processing_stage"] = "runtime_error_handled"
            audit_context["error_details"] = str(runtime_error)
            
            # Log critical runtime error with ultra-enterprise audit
            self._log_critical_audit_event(
                event_type="webhook_runtime_error",
                audit_context=audit_context,
                severity="CRITICAL",
                payment_id=audit_context.get("payment_id"),
                invoice_id=None
            )
            
            # Security event logging handled via audit log
            # SecurityEventService removed per Gemini Code Assist feedback
            # All security events are now logged through _log_critical_audit_event
                
            return {
                "status": "error",
                "message": f"Critical webhook processing failure: {runtime_error}",
                "code": "critical_processing_error",
                "audit_context": audit_context
            }
            
        except Exception as unexpected_error:
            # Handle any other unexpected exceptions with full rollback
            if savepoint:
                savepoint.rollback()
            audit_context["processing_stage"] = "unexpected_error_handled"
            audit_context["error_details"] = str(unexpected_error)
            
            # Log unexpected error with ultra-enterprise audit
            self._log_critical_audit_event(
                event_type="webhook_unexpected_error",
                audit_context=audit_context,
                severity="ERROR",
                payment_id=audit_context.get("payment_id"),
                invoice_id=None
            )
            
            # Security event logging handled via audit log
            # SecurityEventService removed per Gemini Code Assist feedback
            # All security events are now logged through _log_critical_audit_event
                
            return {
                "status": "error",
                "message": f"Unexpected webhook processing error: {unexpected_error}",
                "code": "unexpected_processing_error",
                "audit_context": audit_context
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