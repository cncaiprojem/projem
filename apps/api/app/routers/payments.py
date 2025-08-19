"""Payment API routes for Task 4.6 - Payment provider abstraction."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import get_current_user
from ..models.payment import Payment
from ..models.user import User
from ..schemas.payment import (
    PaymentIntentRequest,
    PaymentIntentResponse,
    PaymentStatusResponse,
    WebhookResponse,
)
from ..services.payment_service import PaymentService
from ..services.rate_limiting_service import RateLimitingService
from ..services.security_event_service import SecurityEventService

# Initialize router
router = APIRouter(prefix="/payments", tags=["payments"])

# Security
security = HTTPBearer()

# Ultra-enterprise error code to HTTP status mapping for banking-grade error handling
WEBHOOK_ERROR_STATUS_MAP = {
    "invalid_signature": status.HTTP_400_BAD_REQUEST,
    "missing_event_id": status.HTTP_400_BAD_REQUEST,
    "missing_payment_id": status.HTTP_400_BAD_REQUEST,
    "payment_not_found": status.HTTP_404_NOT_FOUND,
    "integrity_violation": status.HTTP_409_CONFLICT,
    "idempotency_error": status.HTTP_409_CONFLICT,
    "critical_processing_error": status.HTTP_500_INTERNAL_SERVER_ERROR,
    "unexpected_processing_error": status.HTTP_500_INTERNAL_SERVER_ERROR,
    "webhook_rollback_failure": status.HTTP_500_INTERNAL_SERVER_ERROR,
}

@router.post(
    "/intents",
    response_model=PaymentIntentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create payment intent",
    description="Create a payment intent for an invoice using specified provider"
)
async def create_payment_intent(
    request: PaymentIntentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> PaymentIntentResponse:
    """Create a payment intent for an invoice - Task 4.6 specification."""
    try:
        payment_service = PaymentService(db)
<<<<<<< HEAD
        
=======

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
        # Create payment intent
        payment, client_params = await payment_service.create_payment_intent(
            invoice_id=request.invoice_id,
            provider_name=request.provider
        )
<<<<<<< HEAD
        
        # Commit the transaction atomically
        db.commit()
        
=======

        # Commit the transaction atomically
        db.commit()

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
        return PaymentIntentResponse(
            client_secret=client_params.get("client_secret"),
            provider=client_params["provider"],
            provider_payment_id=client_params["provider_payment_id"],
            amount_cents=client_params["amount_cents"],
            currency=client_params["currency"]
        )
<<<<<<< HEAD
        
=======

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.get(
    "/{payment_id}",
    response_model=PaymentStatusResponse,
    summary="Get payment status",
    description="Get current payment status and details"
)
def get_payment_status(
    payment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> PaymentStatusResponse:
    """Get payment status - Task 4.6 specification."""
    try:
        payment_service = PaymentService(db)
        payment = payment_service.get_payment_status(payment_id)
<<<<<<< HEAD
        
=======

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment {payment_id} not found"
            )
<<<<<<< HEAD
        
=======

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
        return PaymentStatusResponse(
            id=payment.id,
            invoice_id=payment.invoice_id,
            provider=payment.provider,
            provider_payment_id=payment.provider_payment_id,
            amount_decimal=payment.amount_decimal,
            currency=payment.currency,
            status=payment.status,
            created_at=payment.created_at,
            updated_at=payment.updated_at
        )
<<<<<<< HEAD
        
=======

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )


@router.post(
    "/webhook",
    response_model=WebhookResponse,
    summary="Process payment webhook",
    description="Process webhook events from payment providers with idempotency"
)
async def process_webhook(
    request: Request,
    db: Session = Depends(get_db)
) -> WebhookResponse:
    """Process payment webhook with idempotency - Task 4.6 specification."""
    try:
        # Apply rate limiting for webhooks
        rate_limiter = RateLimitingService()
        client_ip = request.client.host if request.client else "unknown"
<<<<<<< HEAD
        
=======

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
        if not await rate_limiter.check_rate_limit(
            key=f"webhook:{client_ip}",
            limit=100,  # 100 webhooks per minute per IP
            window=60
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded for webhook processing"
            )
<<<<<<< HEAD
        
        # Get webhook signature from headers
        signature = request.headers.get("stripe-signature") or request.headers.get("webhook-signature", "")
=======

        # Get webhook signature from headers
        signature = (
            request.headers.get("stripe-signature") or
            request.headers.get("webhook-signature", "")
        )
>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
        if not signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing webhook signature"
            )
<<<<<<< HEAD
        
        # Get raw payload
        raw_payload = await request.body()
        
=======

        # Get raw payload
        raw_payload = await request.body()

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
        # Parse JSON payload
        try:
            parsed_payload = json.loads(raw_payload.decode('utf-8'))
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
<<<<<<< HEAD
        
=======

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
        # Determine provider from headers or payload
        provider = "stripe"  # Default to stripe
        if "mock" in request.headers.get("user-agent", "").lower():
            provider = "mock"
<<<<<<< HEAD
        
        # Process webhook
        payment_service = PaymentService(db)
        result = payment_service.process_webhook_event(
            provider=provider,
            signature=signature,
            payload=raw_payload,
            parsed_payload=parsed_payload
        )
        
        # Commit webhook processing transaction atomically
        if result["status"] == "success":
            db.commit()
        
        if result["status"] == "error":
            # Determine appropriate HTTP status based on error type
            error_code = result.get("code", "")
            if error_code == "invalid_signature":
                status_code = status.HTTP_400_BAD_REQUEST
            elif error_code in ["missing_event_id", "missing_payment_id"]:
                status_code = status.HTTP_400_BAD_REQUEST
            elif error_code == "payment_not_found":
                status_code = status.HTTP_404_NOT_FOUND
            else:
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
                
            raise HTTPException(
                status_code=status_code,
                detail=result["message"]
            )
        
        return WebhookResponse(
            status=result["status"],
            message=result["message"],
            event_id=result.get("event_id"),
            action=result.get("action"),
            code=result.get("code")
        )
        
=======

        # Process webhook with ultra-enterprise banking-grade transaction management
        # Initialize comprehensive audit context
        transaction_audit = {
            "transaction_id": None,
            "webhook_provider": provider,
            "client_ip": client_ip,
            "processing_start": None,
            "processing_stage": "initialization",
            "rollback_reason": None
        }
        
        try:
            # Start explicit transaction for banking-grade consistency
            transaction_start = time.time()
            transaction_audit["processing_start"] = datetime.now(timezone.utc).isoformat()
            transaction_audit["processing_stage"] = "transaction_started"
            
            # Begin explicit database transaction
            db.begin()
            transaction_audit["transaction_id"] = f"webhook_{int(transaction_start)}_{client_ip}"
            transaction_audit["processing_stage"] = "service_processing"
            
            # Process webhook through service layer
            payment_service = PaymentService(db)
            result = payment_service.process_webhook_event(
                provider=provider,
                signature=signature,
                payload=raw_payload,
                parsed_payload=parsed_payload
            )
            
            # Ultra-enterprise transaction decision logic
            transaction_audit["processing_stage"] = "transaction_decision"
            transaction_audit["service_result_status"] = result.get("status")
            transaction_audit["service_result_code"] = result.get("code")
            
            # CRITICAL FIX: Always commit or rollback based on service result
            # This addresses the Copilot feedback about conditional commits leaving transactions incomplete
            if result["status"] == "success":
                # Success: commit all changes atomically
                transaction_audit["processing_stage"] = "committing_transaction"
                try:
                    db.commit()
                    transaction_audit["processing_stage"] = "transaction_committed"
                    transaction_audit["transaction_outcome"] = "committed"
                except Exception as commit_error:
                    transaction_audit["processing_stage"] = "commit_failed"
                    transaction_audit["error_details"] = str(commit_error)
                    # Critical: rollback on commit failure
                    db.rollback()
                    transaction_audit["transaction_outcome"] = "rolled_back_on_commit_failure"
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=f"Transaction commit failed: {commit_error}"
                    )
                    
            elif result["status"] == "error":
                # Error: explicit rollback to ensure consistency
                transaction_audit["processing_stage"] = "rolling_back_transaction"
                transaction_audit["rollback_reason"] = result.get("message", "Service processing error")
                try:
                    db.rollback()
                    transaction_audit["processing_stage"] = "transaction_rolled_back"
                    transaction_audit["transaction_outcome"] = "rolled_back"
                except Exception as rollback_error:
                    transaction_audit["processing_stage"] = "rollback_failed"
                    transaction_audit["error_details"] = str(rollback_error)
                    transaction_audit["transaction_outcome"] = "rollback_failed"
                    
                    # Log critical rollback failure but continue with error response
                    try:
                        security_service = SecurityEventService()
                        security_service.log_critical_error(
                            event_type="webhook_rollback_failure_critical",
                            details={
                                "transaction_audit": transaction_audit,
                                "rollback_error": str(rollback_error),
                                "payment_provider": provider,
                                "client_ip": client_ip,
                                "severity": "CRITICAL",
                                "requires_immediate_attention": True
                            }
                        )
                    except Exception:
                        # Even security logging failed - ultimate fallback to basic logging
                        logger = logging.getLogger(__name__)
                        logger.critical(f"CRITICAL: Transaction rollback failed AND security logging failed: {rollback_error}")
                    
                # Determine appropriate HTTP status based on error type using enterprise mapping
                error_code = result.get("code", "")
                status_code = WEBHOOK_ERROR_STATUS_MAP.get(error_code, status.HTTP_500_INTERNAL_SERVER_ERROR)

                raise HTTPException(
                    status_code=status_code,
                    detail=result["message"]
                )
            else:
                # Unexpected status: rollback and fail safely
                transaction_audit["processing_stage"] = "unexpected_status_rollback"
                transaction_audit["rollback_reason"] = f"Unexpected service status: {result.get('status')}"
                db.rollback()
                transaction_audit["transaction_outcome"] = "rolled_back_unexpected_status"
                
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Unexpected webhook processing status: {result.get('status')}"
                )
            
            # Log successful transaction processing
            transaction_audit["processing_stage"] = "response_preparation"
            transaction_processing_time = time.time() - transaction_start
            transaction_audit["processing_time_seconds"] = round(transaction_processing_time, 4)
            
            # Enhanced response with transaction audit
            response = WebhookResponse(
                status=result["status"],
                message=result["message"],
                event_id=result.get("event_id"),
                action=result.get("action"),
                code=result.get("code")
            )
            
            return response
            
        except HTTPException:
            # Re-raise HTTP exceptions (already handled above)
            raise
            
        except Exception as unexpected_router_error:
            # Handle any unexpected router-level exceptions
            transaction_audit["processing_stage"] = "unexpected_router_error"
            transaction_audit["error_details"] = str(unexpected_router_error)
            transaction_audit["rollback_reason"] = f"Unexpected router error: {unexpected_router_error}"
            
            # Ensure transaction rollback on any unexpected error
            try:
                db.rollback()
                transaction_audit["transaction_outcome"] = "rolled_back_router_error"
            except Exception as rollback_error:
                transaction_audit["rollback_error"] = str(rollback_error)
                transaction_audit["transaction_outcome"] = "rollback_failed_router_error"
            
            # Log critical router error for investigation
            try:
                security_service = SecurityEventService()
                security_service.log_critical_error(
                    event_type="webhook_router_critical_error",
                    details=transaction_audit
                )
            except Exception:
                pass  # Don't fail webhook processing due to logging issues
            
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Critical webhook router error: {unexpected_router_error}"
            )
            
        finally:
            # Always ensure transaction is in a consistent state
            # This is a safety net in case any path above missed cleanup
            try:
                if db.in_transaction():
                    # If we're still in a transaction at this point, something went wrong
                    transaction_audit["processing_stage"] = "final_safety_rollback"
                    transaction_audit["final_safety_rollback"] = True
                    transaction_audit["final_safety_rollback_reason"] = "Transaction still active in finally block"
                    
                    # Log the safety rollback for monitoring
                    logger = logging.getLogger(__name__)
                    logger.warning(f"SAFETY_ROLLBACK: Transaction still active in finally block, forcing rollback", extra={
                        "transaction_audit": transaction_audit,
                        "safety_rollback": True,
                        "requires_investigation": True
                    })
                    
                    # Perform the safety rollback
                    db.rollback()
                    
                    # Additional security logging for safety rollbacks
                    try:
                        security_service = SecurityEventService()
                        security_service.log_critical_error(
                            event_type="webhook_safety_rollback_executed",
                            details={
                                "transaction_audit": transaction_audit,
                                "rollback_reason": "Final safety net activated",
                                "severity": "WARNING",
                                "requires_monitoring": True
                            }
                        )
                    except Exception:
                        pass  # Don't fail if security logging fails
                        
            except Exception as safety_rollback_error:
                # Even the safety rollback failed - this is a critical system issue
                transaction_audit["safety_rollback_error"] = str(safety_rollback_error)
                transaction_audit["critical_system_issue"] = True
                
                # Log critical system failure
                try:
                    logger = logging.getLogger(__name__)
                    logger.critical(f"CRITICAL_SYSTEM_FAILURE: Safety rollback failed in webhook processing", extra={
                        "transaction_audit": transaction_audit,
                        "safety_rollback_error": str(safety_rollback_error),
                        "requires_immediate_attention": True,
                        "system_integrity_compromised": True
                    })
                except Exception:
                    pass  # Ultimate fallback - even logging failed

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook processing failed: {str(e)}"
        )


@router.get(
    "/provider/{provider_name}/payment/{provider_payment_id}",
    response_model=PaymentStatusResponse,
    summary="Get payment by provider ID",
    description="Get payment details using provider payment ID"
)
def get_payment_by_provider_id(
    provider_name: str,
    provider_payment_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> PaymentStatusResponse:
    """Get payment by provider payment ID - Task 4.6 specification."""
    try:
        payment_service = PaymentService(db)
        payment = payment_service.get_payment_by_provider_id(provider_name, provider_payment_id)
<<<<<<< HEAD
        
=======

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment not found for provider {provider_name} with ID {provider_payment_id}"
            )
<<<<<<< HEAD
        
=======

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
        return PaymentStatusResponse(
            id=payment.id,
            invoice_id=payment.invoice_id,
            provider=payment.provider,
            provider_payment_id=payment.provider_payment_id,
            amount_decimal=payment.amount_decimal,
            currency=payment.currency,
            status=payment.status,
            created_at=payment.created_at,
            updated_at=payment.updated_at
        )
<<<<<<< HEAD
        
=======

>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
<<<<<<< HEAD
        )
=======
        )
>>>>>>> origin/fix/pr121-all-gemini-copilot-feedback
