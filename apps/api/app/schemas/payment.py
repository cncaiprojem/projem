"""Payment schemas for Task 4.6."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, validator

from ..models.enums import Currency, PaymentStatus


class PaymentIntentRequest(BaseModel):
    """Request to create a payment intent."""
    
    invoice_id: int = Field(..., description="Invoice ID to create payment for")
    provider: str = Field(default="mock", description="Payment provider to use")
    
    @validator("provider")
    def validate_provider(cls, v):
        """Validate provider is supported."""
        supported_providers = ["stripe", "mock"]
        if v not in supported_providers:
            raise ValueError(f"Unsupported provider. Supported: {supported_providers}")
        return v


class PaymentIntentResponse(BaseModel):
    """Response from creating a payment intent."""
    
    client_secret: Optional[str] = Field(None, description="Client secret for frontend")
    provider: str = Field(..., description="Payment provider used")
    provider_payment_id: str = Field(..., description="Provider payment intent ID")
    amount_cents: int = Field(..., description="Payment amount in cents")
    currency: str = Field(..., description="Payment currency")
    
    class Config:
        from_attributes = True


class PaymentStatusResponse(BaseModel):
    """Response for payment status."""
    
    id: int = Field(..., description="Payment ID")
    invoice_id: int = Field(..., description="Associated invoice ID")
    provider: str = Field(..., description="Payment provider")
    provider_payment_id: str = Field(..., description="Provider payment ID")
    amount_decimal: Decimal = Field(..., description="Payment amount as decimal")
    currency: Currency = Field(..., description="Payment currency")
    status: PaymentStatus = Field(..., description="Payment status")
    created_at: datetime = Field(..., description="Payment creation timestamp")
    updated_at: datetime = Field(..., description="Payment last update timestamp")
    
    class Config:
        from_attributes = True


class WebhookRequest(BaseModel):
    """Request for webhook processing."""
    
    # This will be validated at the router level
    # Raw data will be processed directly
    pass


class WebhookResponse(BaseModel):
    """Response from webhook processing."""
    
    status: str = Field(..., description="Processing status (success/error)")
    message: str = Field(..., description="Processing message")
    event_id: Optional[str] = Field(None, description="Webhook event ID")
    action: Optional[str] = Field(None, description="Action performed")
    code: Optional[str] = Field(None, description="Error code if applicable")


class PaymentAuditLogResponse(BaseModel):
    """Payment audit log entry."""
    
    id: int = Field(..., description="Audit log ID")
    payment_id: Optional[int] = Field(None, description="Associated payment ID")
    invoice_id: Optional[int] = Field(None, description="Associated invoice ID")
    action: str = Field(..., description="Action performed")
    actor_type: str = Field(..., description="Actor type (system, webhook, user)")
    actor_id: Optional[str] = Field(None, description="Actor identifier")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")
    created_at: datetime = Field(..., description="Audit log creation timestamp")
    
    class Config:
        from_attributes = True


class PaymentWebhookEventResponse(BaseModel):
    """Payment webhook event entry."""
    
    id: int = Field(..., description="Webhook event ID")
    event_id: str = Field(..., description="Unique provider event ID")
    provider: str = Field(..., description="Payment provider")
    event_type: str = Field(..., description="Event type")
    payment_id: Optional[int] = Field(None, description="Associated payment ID")
    processed: bool = Field(..., description="Whether event was processed")
    processed_at: Optional[datetime] = Field(None, description="When event was processed")
    created_at: datetime = Field(..., description="Event creation timestamp")
    
    class Config:
        from_attributes = True