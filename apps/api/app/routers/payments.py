"""Payment API routes for Task 4.6 - Payment provider abstraction."""

from __future__ import annotations

import json
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
    WebhookResponse
)
from ..services.payment_service import PaymentService
from ..services.rate_limiting_service import RateLimitingService

# Initialize router
router = APIRouter(prefix="/payments", tags=["payments"])

# Security
security = HTTPBearer()


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
        
        # Create payment intent
        payment, client_params = await payment_service.create_payment_intent(
            invoice_id=request.invoice_id,
            provider_name=request.provider
        )
        
        # Commit the transaction atomically
        db.commit()
        
        return PaymentIntentResponse(
            client_secret=client_params.get("client_secret"),
            provider=client_params["provider"],
            provider_payment_id=client_params["provider_payment_id"],
            amount_cents=client_params["amount_cents"],
            currency=client_params["currency"]
        )
        
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
        
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment {payment_id} not found"
            )
        
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
        
        if not await rate_limiter.check_rate_limit(
            key=f"webhook:{client_ip}",
            limit=100,  # 100 webhooks per minute per IP
            window=60
        ):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded for webhook processing"
            )
        
        # Get webhook signature from headers
        signature = request.headers.get("stripe-signature") or request.headers.get("webhook-signature", "")
        if not signature:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing webhook signature"
            )
        
        # Get raw payload
        raw_payload = await request.body()
        
        # Parse JSON payload
        try:
            parsed_payload = json.loads(raw_payload.decode('utf-8'))
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload"
            )
        
        # Determine provider from headers or payload
        provider = "stripe"  # Default to stripe
        if "mock" in request.headers.get("user-agent", "").lower():
            provider = "mock"
        
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
        
        if not payment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Payment not found for provider {provider_name} with ID {provider_payment_id}"
            )
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server error: {str(e)}"
        )