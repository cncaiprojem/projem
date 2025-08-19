"""
Tests for Task 4.11: Concurrency and uniqueness guards.
Tests invoice numbering, idempotency, and webhook deduplication.
"""

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.idempotency import IdempotencyKey
from app.models.invoice import Invoice
from app.models.license import License
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.models.enums import LicenseType, LicenseStatus, InvoiceStatus
from app.services.invoice_numbering_service import invoice_numbering_service
from app.middleware.idempotency import idempotency_middleware


class TestInvoiceNumbering:
    """Test invoice numbering with concurrency guards."""
    
    def test_generate_invoice_number_sequential(self, db: Session):
        """Test sequential invoice number generation."""
        # Generate first number
        number1 = invoice_numbering_service.generate_invoice_number(
            db=db,
            invoice_date=datetime(2025, 1, 15, tzinfo=timezone.utc)
        )
        
        assert number1.startswith("202501-")
        assert number1.endswith("-CNCAI")
        assert number1 == "202501-00001-CNCAI"
        
        # Generate second number
        number2 = invoice_numbering_service.generate_invoice_number(
            db=db,
            invoice_date=datetime(2025, 1, 20, tzinfo=timezone.utc)
        )
        
        assert number2 == "202501-00002-CNCAI"
        
        # Generate number for different month
        number3 = invoice_numbering_service.generate_invoice_number(
            db=db,
            invoice_date=datetime(2025, 2, 1, tzinfo=timezone.utc)
        )
        
        assert number3 == "202502-00001-CNCAI"
    
    def test_invoice_number_uniqueness(self, db: Session):
        """Test that invoice numbers are unique."""
        numbers = set()
        
        for i in range(10):
            number = invoice_numbering_service.generate_invoice_number(
                db=db,
                invoice_date=datetime(2025, 1, 1, tzinfo=timezone.utc)
            )
            assert number not in numbers
            numbers.add(number)
        
        assert len(numbers) == 10
    
    @pytest.mark.asyncio
    async def test_concurrent_invoice_generation(self, db: Session):
        """Test concurrent invoice number generation (100x parallel)."""
        
        async def generate_number(session: Session, index: int) -> str:
            """Generate invoice number in parallel."""
            return invoice_numbering_service.generate_invoice_number(
                db=session,
                invoice_date=datetime(2025, 3, 1, tzinfo=timezone.utc)
            )
        
        # Create 100 concurrent tasks
        tasks = []
        for i in range(100):
            # Each task needs its own session to simulate real concurrency
            task = asyncio.create_task(generate_number(db, i))
            tasks.append(task)
        
        # Wait for all tasks to complete
        numbers = await asyncio.gather(*tasks)
        
        # Check all numbers are unique
        unique_numbers = set(numbers)
        assert len(unique_numbers) == 100, f"Duplicate numbers found: {len(numbers) - len(unique_numbers)} duplicates"
        
        # Check all numbers are in correct format
        for number in numbers:
            assert number.startswith("202503-")
            assert number.endswith("-CNCAI")
        
        # Check sequence is correct (numbers should be 00001 to 00100)
        sequence_numbers = sorted([
            int(num.split("-")[1]) for num in numbers
        ])
        assert sequence_numbers == list(range(1, 101))
    
    def test_invoice_with_generated_number(self, db: Session, test_user: User):
        """Test creating invoice with generated number."""
        # Generate number
        invoice_number = invoice_numbering_service.generate_invoice_number(db)
        
        # Create invoice
        invoice = Invoice(
            user_id=test_user.id,
            number=invoice_number,
            amount_cents=100000,  # 1000.00 TRY
            status=InvoiceStatus.DRAFT
        )
        
        db.add(invoice)
        db.commit()
        db.refresh(invoice)
        
        assert invoice.number == invoice_number
        assert invoice.amount_decimal == Decimal("1000.00")
        
        # Try to create another invoice with same number (should fail)
        duplicate_invoice = Invoice(
            user_id=test_user.id,
            number=invoice_number,  # Same number
            amount_cents=50000,
            status=InvoiceStatus.DRAFT
        )
        
        db.add(duplicate_invoice)
        with pytest.raises(Exception):  # IntegrityError
            db.commit()
        db.rollback()


class TestIdempotency:
    """Test API idempotency functionality."""
    
    def test_idempotency_key_creation(self, db: Session, test_user: User):
        """Test creating idempotency key."""
        key = IdempotencyKey.create_for_request(
            user_id=test_user.id,
            key="test-key-123",
            request_path="/api/v1/licenses/assign",
            request_method="POST",
            request_hash=hashlib.sha256(b"test body").hexdigest(),
            ttl_hours=24
        )
        
        db.add(key)
        db.commit()
        db.refresh(key)
        
        assert key.user_id == test_user.id
        assert key.key == "test-key-123"
        assert key.is_processing is True
        assert not key.is_expired()
    
    @pytest.mark.asyncio
    async def test_idempotency_duplicate_detection(self, db: Session, test_user: User):
        """Test detecting duplicate requests with same idempotency key."""
        request_body = b'{"test": "data"}'
        
        # First request - should return None (not cached)
        result = await idempotency_middleware.check_idempotency(
            db=db,
            user_id=test_user.id,
            idempotency_key="duplicate-test",
            request_path="/api/v1/licenses/assign",
            request_method="POST",
            request_body=request_body
        )
        
        assert result is None
        
        # Store the key
        idempotency_obj = idempotency_middleware.store_idempotency_key(
            db=db,
            user_id=test_user.id,
            idempotency_key="duplicate-test",
            request_path="/api/v1/licenses/assign",
            request_method="POST",
            request_body=request_body
        )
        
        # Complete the request
        response_body = {"success": True, "license_id": 123}
        idempotency_middleware.complete_request(
            db=db,
            idempotency_obj=idempotency_obj,
            response_status=200,
            response_body=response_body
        )
        
        # Second request with same key - should return cached response
        result = await idempotency_middleware.check_idempotency(
            db=db,
            user_id=test_user.id,
            idempotency_key="duplicate-test",
            request_path="/api/v1/licenses/assign",
            request_method="POST",
            request_body=request_body
        )
        
        assert result is not None
        assert result["status_code"] == 200
        assert result["body"] == response_body
    
    @pytest.mark.asyncio
    async def test_idempotency_different_body_error(self, db: Session, test_user: User):
        """Test that using same key with different body raises error."""
        # Store first request
        idempotency_obj = idempotency_middleware.store_idempotency_key(
            db=db,
            user_id=test_user.id,
            idempotency_key="mismatch-test",
            request_path="/api/v1/licenses/assign",
            request_method="POST",
            request_body=b'{"original": "body"}'
        )
        
        idempotency_middleware.complete_request(
            db=db,
            idempotency_obj=idempotency_obj,
            response_status=200,
            response_body={"success": True}
        )
        
        # Try with different body - should raise HTTPException
        with pytest.raises(Exception) as exc_info:
            await idempotency_middleware.check_idempotency(
                db=db,
                user_id=test_user.id,
                idempotency_key="mismatch-test",
                request_path="/api/v1/licenses/assign",
                request_method="POST",
                request_body=b'{"different": "body"}'  # Different body
            )
        
        assert "IDEMPOTENCY_KEY_MISMATCH" in str(exc_info.value)
    
    def test_idempotency_cleanup(self, db: Session, test_user: User):
        """Test cleanup of expired idempotency keys."""
        # Create expired key
        expired_key = IdempotencyKey(
            user_id=test_user.id,
            key="expired-key",
            request_path="/test",
            request_method="POST",
            request_hash="hash",
            response_status=200,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1)  # Expired
        )
        
        # Create valid key
        valid_key = IdempotencyKey(
            user_id=test_user.id,
            key="valid-key",
            request_path="/test",
            request_method="POST",
            request_hash="hash",
            response_status=200,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1)  # Not expired
        )
        
        db.add_all([expired_key, valid_key])
        db.commit()
        
        # Run cleanup
        deleted_count = idempotency_middleware.cleanup_expired_keys(db)
        
        assert deleted_count == 1
        
        # Check only valid key remains
        remaining = db.query(IdempotencyKey).all()
        assert len(remaining) == 1
        assert remaining[0].key == "valid-key"


class TestWebhookDeduplication:
    """Test webhook event deduplication."""
    
    def test_webhook_event_creation(self, db: Session, test_user: User):
        """Test creating webhook event."""
        event = WebhookEvent.create_event(
            event_id="evt_123456",
            event_type="license.expired",
            entity_type="license",
            entity_id=42,
            webhook_url="https://example.com/webhook",
            payload={"license_id": 42, "user_id": test_user.id},
            user_id=test_user.id
        )
        
        db.add(event)
        db.commit()
        db.refresh(event)
        
        assert event.event_id == "evt_123456"
        assert event.status == "pending"
        assert event.should_retry()
    
    def test_webhook_duplicate_prevention(self, db: Session):
        """Test that duplicate webhook events are prevented."""
        # Create first event
        event1 = WebhookEvent(
            event_id="duplicate_evt_001",
            event_type="payment.completed",
            entity_type="payment",
            entity_id=100,
            webhook_url="https://example.com/webhook",
            payload={"payment_id": 100}
        )
        
        db.add(event1)
        db.commit()
        
        # Try to create duplicate with same event_id
        event2 = WebhookEvent(
            event_id="duplicate_evt_001",  # Same event_id
            event_type="payment.completed",
            entity_type="payment",
            entity_id=100,
            webhook_url="https://example.com/webhook",
            payload={"payment_id": 100}
        )
        
        db.add(event2)
        with pytest.raises(Exception):  # IntegrityError
            db.commit()
        db.rollback()
    
    def test_webhook_retry_logic(self, db: Session):
        """Test webhook retry with exponential backoff."""
        event = WebhookEvent(
            event_id="retry_test_001",
            event_type="invoice.created",
            entity_type="invoice",
            entity_id=200,
            webhook_url="https://example.com/webhook",
            payload={"invoice_id": 200}
        )
        
        db.add(event)
        db.commit()
        
        # Simulate first failure
        event.mark_failed("Connection timeout", response_status=None)
        db.commit()
        
        assert event.retry_count == 1
        assert event.status == "pending"
        assert event.next_retry_at is not None
        
        # Simulate more failures
        for i in range(2, 6):
            event.mark_failed(f"Failure {i}", response_status=500)
            db.commit()
            
            if i < 5:
                assert event.status == "pending"
                assert event.should_retry()
            else:
                # After 5 retries, should be failed
                assert event.status == "failed"
                assert not event.should_retry()
    
    def test_webhook_lock_acquisition(self, db: Session):
        """Test webhook processing lock mechanism."""
        event = WebhookEvent(
            event_id="lock_test_001",
            event_type="job.completed",
            entity_type="job",
            entity_id=300,
            webhook_url="https://example.com/webhook",
            payload={"job_id": 300}
        )
        
        db.add(event)
        db.commit()
        
        # Acquire lock
        worker1_locked = event.acquire_lock("worker_1")
        db.commit()
        
        assert worker1_locked is True
        assert event.locked_by == "worker_1"
        assert event.locked_at is not None
        
        # Try to acquire with different worker (should fail)
        worker2_locked = event.acquire_lock("worker_2", lock_timeout_seconds=300)
        
        assert worker2_locked is False
        assert event.locked_by == "worker_1"  # Still locked by worker_1
        
        # Release lock
        event.release_lock()
        db.commit()
        
        assert event.locked_by is None
        assert event.locked_at is None
        
        # Now worker_2 can acquire
        worker2_locked = event.acquire_lock("worker_2")
        db.commit()
        
        assert worker2_locked is True
        assert event.locked_by == "worker_2"


class TestUniqueLicenseConstraint:
    """Test unique active license per user constraint."""
    
    def test_single_active_license_allowed(self, db: Session, test_user: User):
        """Test that only one active license is allowed per user."""
        # Create first active license
        license1 = License(
            user_id=test_user.id,
            plan=LicenseType.BASIC,
            status=LicenseStatus.ACTIVE,
            seats=1,
            starts_at=datetime.now(timezone.utc),
            ends_at=datetime.now(timezone.utc) + timedelta(days=30)
        )
        
        db.add(license1)
        db.commit()
        
        # Try to create second active license
        license2 = License(
            user_id=test_user.id,
            plan=LicenseType.PROFESSIONAL,
            status=LicenseStatus.ACTIVE,  # Also active
            seats=5,
            starts_at=datetime.now(timezone.utc),
            ends_at=datetime.now(timezone.utc) + timedelta(days=60)
        )
        
        db.add(license2)
        with pytest.raises(Exception):  # IntegrityError due to unique constraint
            db.commit()
        db.rollback()
    
    def test_multiple_inactive_licenses_allowed(self, db: Session, test_user: User):
        """Test that multiple inactive licenses are allowed per user."""
        # Create expired license
        expired_license = License(
            user_id=test_user.id,
            plan=LicenseType.TRIAL,
            status=LicenseStatus.EXPIRED,
            seats=1,
            starts_at=datetime.now(timezone.utc) - timedelta(days=60),
            ends_at=datetime.now(timezone.utc) - timedelta(days=30)
        )
        
        # Create cancelled license
        cancelled_license = License(
            user_id=test_user.id,
            plan=LicenseType.BASIC,
            status=LicenseStatus.CANCELLED,
            seats=1,
            starts_at=datetime.now(timezone.utc) - timedelta(days=30),
            ends_at=datetime.now(timezone.utc) + timedelta(days=30)
        )
        
        # Create pending license
        pending_license = License(
            user_id=test_user.id,
            plan=LicenseType.PROFESSIONAL,
            status=LicenseStatus.PENDING,
            seats=5,
            starts_at=datetime.now(timezone.utc) + timedelta(days=1),
            ends_at=datetime.now(timezone.utc) + timedelta(days=31)
        )
        
        db.add_all([expired_license, cancelled_license, pending_license])
        db.commit()  # Should succeed - no active licenses
        
        # Verify all were created
        licenses = db.query(License).filter(License.user_id == test_user.id).all()
        assert len(licenses) == 3
        assert all(l.status != LicenseStatus.ACTIVE for l in licenses)


@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user for the tests."""
    user = User(
        email=f"test_{uuid.uuid4()}@example.com",
        full_name="Test User",
        hashed_password="dummy_hash"
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user