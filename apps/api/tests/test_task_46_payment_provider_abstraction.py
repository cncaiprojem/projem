"""
Test suite for Task 4.6: Payment provider abstraction and webhook handling with idempotency
"""

import json
import pytest
import uuid
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock

from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from ..app.models.enums import Currency, PaymentStatus, PaidStatus
from ..app.models.invoice import Invoice
from ..app.models.payment import Payment, PaymentWebhookEvent, PaymentAuditLog
from ..app.models.user import User
from ..app.models.license import License
from ..app.services.payment_service import PaymentService
from ..app.services.payment_providers import PaymentProviderFactory, MockProvider
from ..app.services.payment_providers.base import PaymentIntent, PaymentResult
from ..app.main import app

# Test client
client = TestClient(app)


class TestPaymentProviders:
    """Test payment provider implementations."""

    async def test_mock_provider_create_intent(self):
        """Test mock provider can create payment intents."""
        provider = MockProvider({"test_mode": True})

        result = await provider.create_intent(
            amount_cents=10000,  # 100.00 TRY
            currency=Currency.TRY,
            metadata={"test": "data"},
        )

        assert result.success
        assert result.payment_intent is not None
        assert result.payment_intent.amount_cents == 10000
        assert result.payment_intent.currency == Currency.TRY
        assert result.payment_intent.status == PaymentStatus.REQUIRES_ACTION
        assert "pi_mock_" in result.payment_intent.provider_payment_id

    async def test_mock_provider_create_intent_with_failure(self):
        """Test mock provider can simulate failures."""
        provider = MockProvider({"test_mode": True, "fail_percentage": 1.0})

        result = await provider.create_intent(amount_cents=10000, currency=Currency.TRY)

        assert not result.success
        assert result.error_message == "Mock payment failure for testing"
        assert result.error_code == "mock_failure"

    async def test_mock_provider_retrieve(self):
        """Test mock provider can retrieve payment intents."""
        provider = MockProvider({"test_mode": True})

        # Test different status patterns
        result = await provider.retrieve("pi_mock_succeeded_123")
        assert result.success
        assert result.payment_intent.status == PaymentStatus.SUCCEEDED

        result = await provider.retrieve("pi_mock_failed_123")
        assert result.success
        assert result.payment_intent.status == PaymentStatus.FAILED

    async def test_mock_provider_confirm(self):
        """Test mock provider can confirm payment intents."""
        provider = MockProvider({"test_mode": True})

        result = await provider.confirm("pi_mock_123")
        assert result.success
        assert result.payment_intent.status == PaymentStatus.SUCCEEDED

        # Test simulated failure
        result = await provider.confirm("pi_mock_123", {"simulate_failure": True})
        assert result.success
        assert result.payment_intent.status == PaymentStatus.FAILED

    def test_mock_provider_verify_webhook(self):
        """Test mock provider webhook verification."""
        provider = MockProvider({"test_mode": True})

        # In test mode, always accepts webhooks
        assert provider.verify_webhook("any_signature", b"any_payload")

        # In strict mode
        provider = MockProvider({"test_mode": False})
        assert provider.verify_webhook("mock_signature", b"payload")
        assert not provider.verify_webhook("wrong_signature", b"payload")

    def test_mock_provider_parse_webhook_event(self):
        """Test mock provider webhook event parsing."""
        provider = MockProvider({"test_mode": True})

        webhook_payload = {
            "id": "evt_test_123",
            "type": "payment_intent.succeeded",
            "data": {
                "object": {
                    "id": "pi_mock_123",
                    "status": "succeeded",
                    "amount": 10000,
                    "currency": "try",
                }
            },
        }

        event_data = provider.parse_webhook_event(webhook_payload)

        assert event_data["event_id"] == "evt_test_123"
        assert event_data["event_type"] == "payment_intent.succeeded"
        assert event_data["provider_payment_id"] == "pi_mock_123"
        assert event_data["status"] == PaymentStatus.SUCCEEDED
        assert event_data["metadata"]["mock_event"]

    def test_payment_provider_factory(self):
        """Test payment provider factory."""
        # Test creating mock provider
        provider = PaymentProviderFactory.create_provider("mock")
        assert isinstance(provider, MockProvider)
        assert provider.provider_name == "mock"

        # Test unsupported provider
        with pytest.raises(ValueError, match="Unsupported payment provider"):
            PaymentProviderFactory.create_provider("unsupported")

        # Test supported providers list
        supported = PaymentProviderFactory.get_supported_providers()
        assert "mock" in supported
        assert "stripe" in supported


class TestPaymentService:
    """Test payment service functionality."""

    @pytest.fixture
    def sample_user(self, db: Session):
        """Create a sample user for testing."""
        user = User(email="test@example.com", username="testuser", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @pytest.fixture
    def sample_license(self, db: Session, sample_user):
        """Create a sample license for testing."""
        license = License(user_id=sample_user.id, plan_name="basic", is_active=True)
        db.add(license)
        db.commit()
        db.refresh(license)
        return license

    @pytest.fixture
    def sample_invoice(self, db: Session, sample_user, sample_license):
        """Create a sample invoice for testing."""
        invoice = Invoice(
            user_id=sample_user.id,
            license_id=sample_license.id,
            number="202501-000001-CNCAI",
            amount=Decimal("100.00"),
            currency="TRY",
            vat=Decimal("20.00"),
            total=Decimal("120.00"),
            paid_status=PaidStatus.UNPAID,
        )
        db.add(invoice)
        db.commit()
        db.refresh(invoice)
        return invoice

    async def test_create_payment_intent_success(self, db: Session, sample_invoice):
        """Test successful payment intent creation."""
        service = PaymentService(db)

        payment, client_params = await service.create_payment_intent(
            invoice_id=sample_invoice.id, provider_name="mock"
        )

        assert payment is not None
        assert payment.invoice_id == sample_invoice.id
        assert payment.provider == "mock"
        assert payment.amount_cents == 12000  # 120.00 TRY in cents
        assert payment.currency == Currency.TRY
        assert payment.status == PaymentStatus.REQUIRES_ACTION

        assert client_params["provider"] == "mock"
        assert client_params["amount_cents"] == 12000
        assert client_params["currency"] == "TRY"
        assert "client_secret" in client_params
        assert "provider_payment_id" in client_params

    async def test_create_payment_intent_invoice_not_found(self, db: Session):
        """Test payment intent creation with non-existent invoice."""
        service = PaymentService(db)

        with pytest.raises(ValueError, match="Invoice 99999 not found"):
            await service.create_payment_intent(invoice_id=99999, provider_name="mock")

    async def test_create_payment_intent_already_paid(self, db: Session, sample_invoice):
        """Test payment intent creation for already paid invoice."""
        sample_invoice.paid_status = PaidStatus.PAID
        db.commit()

        service = PaymentService(db)

        with pytest.raises(ValueError, match="Invoice .* is already paid"):
            await service.create_payment_intent(invoice_id=sample_invoice.id, provider_name="mock")

    def test_get_payment_status(self, db: Session, sample_invoice):
        """Test getting payment status."""
        # Create a payment
        payment = Payment(
            invoice_id=sample_invoice.id,
            provider="mock",
            provider_payment_id="pi_mock_123",
            amount_cents=12000,
            currency=Currency.TRY,
            status=PaymentStatus.SUCCEEDED,
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)

        service = PaymentService(db)
        result = service.get_payment_status(payment.id)

        assert result is not None
        assert result.id == payment.id
        assert result.status == PaymentStatus.SUCCEEDED

        # Test non-existent payment
        result = service.get_payment_status(99999)
        assert result is None

    def test_get_payment_by_provider_id(self, db: Session, sample_invoice):
        """Test getting payment by provider ID."""
        payment = Payment(
            invoice_id=sample_invoice.id,
            provider="mock",
            provider_payment_id="pi_mock_123",
            amount_cents=12000,
            currency=Currency.TRY,
            status=PaymentStatus.SUCCEEDED,
        )
        db.add(payment)
        db.commit()

        service = PaymentService(db)
        result = service.get_payment_by_provider_id("mock", "pi_mock_123")

        assert result is not None
        assert result.provider_payment_id == "pi_mock_123"

        # Test non-existent payment
        result = service.get_payment_by_provider_id("mock", "pi_nonexistent")
        assert result is None


class TestWebhookProcessing:
    """Test webhook processing with idempotency."""

    @pytest.fixture
    def sample_payment(self, db: Session, sample_invoice):
        """Create a sample payment for webhook testing."""
        payment = Payment(
            invoice_id=sample_invoice.id,
            provider="mock",
            provider_payment_id="pi_mock_123",
            amount_cents=12000,
            currency=Currency.TRY,
            status=PaymentStatus.REQUIRES_ACTION,
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)
        return payment

    def test_webhook_processing_success(self, db: Session, sample_payment):
        """Test successful webhook processing."""
        service = PaymentService(db)

        webhook_payload = {
            "id": "evt_test_123",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_mock_123", "status": "succeeded"}},
        }

        result = service.process_webhook_event(
            provider="mock",
            signature="mock_signature",
            payload=json.dumps(webhook_payload).encode(),
            parsed_payload=webhook_payload,
        )

        assert result["status"] == "success"
        assert result["action"] == "payment_succeeded"
        assert result["event_id"] == "evt_test_123"

        # Check payment status updated
        db.refresh(sample_payment)
        assert sample_payment.status == PaymentStatus.SUCCEEDED

        # Check invoice status updated
        db.refresh(sample_payment.invoice)
        assert sample_payment.invoice.paid_status == PaidStatus.PAID

        # Check webhook event recorded
        webhook_event = (
            db.query(PaymentWebhookEvent)
            .filter(PaymentWebhookEvent.event_id == "evt_test_123")
            .first()
        )
        assert webhook_event is not None
        assert webhook_event.processed
        assert webhook_event.payment_id == sample_payment.id

        # Check audit log created
        audit_log = (
            db.query(PaymentAuditLog)
            .filter(
                PaymentAuditLog.payment_id == sample_payment.id,
                PaymentAuditLog.action == "payment_succeeded",
            )
            .first()
        )
        assert audit_log is not None
        assert audit_log.actor_type == "webhook"

    def test_webhook_processing_idempotency(self, db: Session, sample_payment):
        """Test webhook idempotency - duplicate events are ignored."""
        service = PaymentService(db)

        webhook_payload = {
            "id": "evt_test_duplicate",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_mock_123", "status": "succeeded"}},
        }

        # Process webhook first time
        result1 = service.process_webhook_event(
            provider="mock",
            signature="mock_signature",
            payload=json.dumps(webhook_payload).encode(),
            parsed_payload=webhook_payload,
        )

        # Process same webhook again
        result2 = service.process_webhook_event(
            provider="mock",
            signature="mock_signature",
            payload=json.dumps(webhook_payload).encode(),
            parsed_payload=webhook_payload,
        )

        assert result1["status"] == "success"
        assert result2["status"] == "success"
        assert "already processed" in result2["message"]

        # Should only have one webhook event record
        webhook_events = (
            db.query(PaymentWebhookEvent)
            .filter(PaymentWebhookEvent.event_id == "evt_test_duplicate")
            .all()
        )
        assert len(webhook_events) == 1

    def test_webhook_processing_failed_payment(self, db: Session, sample_payment):
        """Test webhook processing for failed payments."""
        service = PaymentService(db)

        webhook_payload = {
            "id": "evt_failed_123",
            "type": "payment_intent.failed",
            "data": {"object": {"id": "pi_mock_123", "status": "failed"}},
        }

        result = service.process_webhook_event(
            provider="mock",
            signature="mock_signature",
            payload=json.dumps(webhook_payload).encode(),
            parsed_payload=webhook_payload,
        )

        assert result["status"] == "success"
        assert result["action"] == "payment_failed"

        # Check payment status updated
        db.refresh(sample_payment)
        assert sample_payment.status == PaymentStatus.FAILED

        # Check invoice status updated
        db.refresh(sample_payment.invoice)
        assert sample_payment.invoice.paid_status == PaidStatus.FAILED

    def test_webhook_processing_invalid_signature(self, db: Session):
        """Test webhook processing with invalid signature."""
        service = PaymentService(db)

        with patch.object(MockProvider, "verify_webhook", return_value=False):
            result = service.process_webhook_event(
                provider="mock",
                signature="invalid_signature",
                payload=b"payload",
                parsed_payload={},
            )

            assert result["status"] == "error"
            assert result["code"] == "invalid_signature"

    def test_webhook_processing_payment_not_found(self, db: Session):
        """Test webhook processing for non-existent payment."""
        service = PaymentService(db)

        webhook_payload = {
            "id": "evt_notfound_123",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_nonexistent_123", "status": "succeeded"}},
        }

        result = service.process_webhook_event(
            provider="mock",
            signature="mock_signature",
            payload=json.dumps(webhook_payload).encode(),
            parsed_payload=webhook_payload,
        )

        assert result["status"] == "error"
        assert result["code"] == "payment_not_found"


class TestPaymentAPI:
    """Test payment API endpoints."""

    def test_create_payment_intent_endpoint(self, db: Session, sample_invoice, auth_headers):
        """Test POST /payments/intents endpoint."""
        response = client.post(
            "/payments/intents",
            json={"invoice_id": sample_invoice.id, "provider": "mock"},
            headers=auth_headers,
        )

        assert response.status_code == 201
        data = response.json()

        assert data["provider"] == "mock"
        assert data["amount_cents"] == 12000
        assert data["currency"] == "TRY"
        assert "client_secret" in data
        assert "provider_payment_id" in data

    def test_create_payment_intent_invalid_provider(self, auth_headers):
        """Test payment intent creation with invalid provider."""
        response = client.post(
            "/payments/intents",
            json={"invoice_id": 1, "provider": "invalid_provider"},
            headers=auth_headers,
        )

        assert response.status_code == 422  # Validation error

    def test_get_payment_status_endpoint(self, db: Session, sample_invoice, auth_headers):
        """Test GET /payments/{payment_id} endpoint."""
        # Create a payment first
        payment = Payment(
            invoice_id=sample_invoice.id,
            provider="mock",
            provider_payment_id="pi_mock_123",
            amount_cents=12000,
            currency=Currency.TRY,
            status=PaymentStatus.SUCCEEDED,
        )
        db.add(payment)
        db.commit()
        db.refresh(payment)

        response = client.get(f"/payments/{payment.id}", headers=auth_headers)

        assert response.status_code == 200
        data = response.json()

        assert data["id"] == payment.id
        assert data["provider"] == "mock"
        assert data["status"] == "succeeded"
        assert data["amount_decimal"] == "120.00"

    def test_get_payment_status_not_found(self, auth_headers):
        """Test getting payment status for non-existent payment."""
        response = client.get("/payments/99999", headers=auth_headers)
        assert response.status_code == 404

    @patch("apps.api.app.services.rate_limiting_service.RateLimitingService.check_rate_limit")
    def test_webhook_endpoint(self, mock_rate_limit, db: Session, sample_payment):
        """Test POST /payments/webhook endpoint."""
        mock_rate_limit.return_value = True  # Allow request

        webhook_payload = {
            "id": "evt_webhook_test",
            "type": "payment_intent.succeeded",
            "data": {"object": {"id": "pi_mock_123", "status": "succeeded"}},
        }

        response = client.post(
            "/payments/webhook",
            json=webhook_payload,
            headers={"webhook-signature": "mock_signature"},
        )

        assert response.status_code == 200
        data = response.json()

        assert data["status"] == "success"
        assert data["action"] == "payment_succeeded"
        assert data["event_id"] == "evt_webhook_test"

    def test_webhook_endpoint_rate_limited(self):
        """Test webhook endpoint with rate limiting."""
        with patch(
            "apps.api.app.services.rate_limiting_service.RateLimitingService.check_rate_limit",
            return_value=False,
        ):
            response = client.post(
                "/payments/webhook", json={}, headers={"webhook-signature": "test"}
            )

            assert response.status_code == 429

    def test_webhook_endpoint_missing_signature(self):
        """Test webhook endpoint without signature."""
        response = client.post("/payments/webhook", json={})
        assert response.status_code == 400
        assert "Missing webhook signature" in response.json()["detail"]


class TestPaymentModels:
    """Test payment model functionality."""

    def test_payment_model_properties(self, db: Session, sample_invoice):
        """Test payment model properties."""
        payment = Payment(
            invoice_id=sample_invoice.id,
            provider="mock",
            provider_payment_id="pi_mock_123",
            amount_cents=12000,
            currency=Currency.TRY,
            status=PaymentStatus.SUCCEEDED,
        )

        assert payment.amount_decimal == Decimal("120.00")
        assert payment.is_successful
        assert not payment.is_pending
        assert not payment.is_failed

        # Test pending status
        payment.status = PaymentStatus.REQUIRES_ACTION
        assert payment.is_pending
        assert not payment.is_successful

        # Test failed status
        payment.status = PaymentStatus.FAILED
        assert payment.is_failed
        assert not payment.is_successful

    def test_payment_model_methods(self, db: Session, sample_invoice):
        """Test payment model methods."""
        payment = Payment(
            invoice_id=sample_invoice.id,
            provider="mock",
            provider_payment_id="pi_mock_123",
            amount_cents=12000,
            currency=Currency.TRY,
            status=PaymentStatus.REQUIRES_ACTION,
        )

        # Test mark_as_succeeded
        payment.mark_as_succeeded()
        assert payment.status == PaymentStatus.SUCCEEDED

        # Test mark_as_failed
        payment.mark_as_failed("Test failure")
        assert payment.status == PaymentStatus.FAILED
        assert payment.raw_response["failure_reason"] == "Test failure"

        # Test mark_as_canceled
        payment.mark_as_canceled()
        assert payment.status == PaymentStatus.CANCELED

    def test_payment_webhook_event_model(self, db: Session):
        """Test payment webhook event model."""
        webhook_event = PaymentWebhookEvent(
            event_id="evt_test_123",
            provider="mock",
            event_type="payment_intent.succeeded",
            raw_event={"test": "data"},
            processed=False,
        )

        assert not webhook_event.processed
        assert webhook_event.processed_at is None

        webhook_event.mark_as_processed()
        assert webhook_event.processed
        assert webhook_event.processed_at is not None

    def test_payment_audit_log_model(self, db: Session, sample_payment):
        """Test payment audit log model."""
        audit_log = PaymentAuditLog.log_payment_event(
            db,
            payment_id=sample_payment.id,
            invoice_id=sample_payment.invoice_id,
            action="payment_succeeded",
            actor_type="webhook",
            actor_id="evt_test_123",
            context={"test": "context"},
        )

        assert audit_log.payment_id == sample_payment.id
        assert audit_log.action == "payment_succeeded"
        assert audit_log.actor_type == "webhook"
        assert audit_log.context["test"] == "context"


class TestFinancialPrecision:
    """Test banking-grade financial precision."""

    def test_amount_cents_precision(self, db: Session, sample_invoice):
        """Test that amounts are stored as cents for precision."""
        # Test with fractional cents (should be rounded)
        payment = Payment(
            invoice_id=sample_invoice.id,
            provider="mock",
            provider_payment_id="pi_precision_test",
            amount_cents=12001,  # 120.01 TRY
            currency=Currency.TRY,
            status=PaymentStatus.SUCCEEDED,
        )

        assert payment.amount_decimal == Decimal("120.01")

        # Test large amounts
        payment.amount_cents = 999999999  # 9,999,999.99 TRY
        assert payment.amount_decimal == Decimal("9999999.99")

    def test_decimal_precision_consistency(self):
        """Test Decimal precision consistency across operations."""
        # Test provider base class methods
        from apps.api.app.services.payment_providers.base import PaymentProvider

        provider = MockProvider({"test_mode": True})

        # Test amount conversion
        amount = Decimal("123.45")
        cents = provider._convert_amount_to_cents(amount)
        back_to_decimal = provider._convert_cents_to_amount(cents)

        assert cents == 12345
        assert back_to_decimal == amount
