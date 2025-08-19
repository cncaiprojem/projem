"""
Comprehensive tests for Task 3.6: Magic Link Issuance and Consumption

This test suite validates ultra enterprise passwordless authentication with:
- Token expiration and single-use enforcement
- Email enumeration protection
- Rate limiting functionality
- Security audit logging
- Integration with existing auth system
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
import json

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.db import get_db
from app.models.user import User
from app.models.magic_link import MagicLink
from app.models.audit_log import AuditLog
from app.models.security_event import SecurityEvent
from app.services.magic_link_service import magic_link_service, MagicLinkError
from app.schemas.magic_link_schemas import MagicLinkRequestRequest, MagicLinkConsumeRequest


class TestMagicLinkModel:
    """Test magic link model functionality."""

    def test_magic_link_creation(self, db: Session):
        """Test magic link model creation."""
        magic_link = MagicLink(
            email="test@example.com",
            nonce="test-nonce-123",
            ip_address="192.168.1.1",
            user_agent="Test Agent",
            device_fingerprint="fp_test123",
        )

        db.add(magic_link)
        db.commit()

        assert magic_link.id is not None
        assert magic_link.email == "test@example.com"
        assert magic_link.nonce == "test-nonce-123"
        assert magic_link.is_valid
        assert not magic_link.is_consumed
        assert not magic_link.is_expired

    def test_magic_link_expiration(self, db: Session):
        """Test magic link expiration logic."""
        # Create expired magic link
        expired_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        magic_link = MagicLink(
            email="test@example.com", nonce="test-nonce-expired", issued_at=expired_time
        )

        db.add(magic_link)
        db.commit()

        assert magic_link.is_expired
        assert not magic_link.is_valid
        assert magic_link.remaining_seconds == 0

    def test_magic_link_consumption(self, db: Session):
        """Test magic link consumption."""
        magic_link = MagicLink(email="test@example.com", nonce="test-nonce-consume")

        db.add(magic_link)
        db.commit()

        # Consume the magic link
        magic_link.consume(
            ip_address="192.168.1.1", user_agent="Test Agent", device_fingerprint="fp_test123"
        )

        db.commit()

        assert magic_link.is_consumed
        assert not magic_link.is_valid
        assert magic_link.consumed_at is not None
        assert magic_link.consumed_ip_address == "192.168.1.1"

    def test_magic_link_invalidation(self, db: Session):
        """Test magic link invalidation."""
        magic_link = MagicLink(email="test@example.com", nonce="test-nonce-invalid")

        db.add(magic_link)
        db.commit()

        # Invalidate the magic link
        magic_link.invalidate("security_revoked")
        db.commit()

        assert not magic_link.is_valid
        assert magic_link.invalidated_at is not None
        assert magic_link.invalidation_reason == "security_revoked"


class TestMagicLinkService:
    """Test magic link service functionality."""

    def test_request_magic_link_existing_user(self, db: Session, test_user: User):
        """Test magic link request for existing user."""
        with patch.object(magic_link_service, "_send_magic_link_email") as mock_email:
            result = magic_link_service.request_magic_link(
                db=db, email=test_user.email, ip_address="192.168.1.1", user_agent="Test Agent"
            )

            assert result is True  # Always returns True for security
            mock_email.assert_called_once()

            # Check magic link was created
            magic_link = db.query(MagicLink).filter(MagicLink.email == test_user.email).first()

            assert magic_link is not None
            assert magic_link.email == test_user.email
            assert magic_link.is_valid

    def test_request_magic_link_nonexistent_user(self, db: Session):
        """Test magic link request for non-existent user."""
        with patch.object(magic_link_service, "_send_magic_link_email") as mock_email:
            result = magic_link_service.request_magic_link(
                db=db,
                email="nonexistent@example.com",
                ip_address="192.168.1.1",
                user_agent="Test Agent",
            )

            assert result is True  # Always returns True for email enumeration protection
            mock_email.assert_not_called()  # No email sent for non-existent user

            # Check no magic link was created
            magic_link = (
                db.query(MagicLink).filter(MagicLink.email == "nonexistent@example.com").first()
            )

            assert magic_link is None

    def test_consume_magic_link_success(self, db: Session, test_user: User):
        """Test successful magic link consumption."""
        # Create magic link
        magic_link = MagicLink(email=test_user.email, nonce="test-nonce-success")
        db.add(magic_link)
        db.commit()

        # Create token
        token = magic_link_service._create_token(
            {
                "email": test_user.email,
                "nonce": "test-nonce-success",
                "iat": int(datetime.now(timezone.utc).timestamp()),
            }
        )

        # Consume magic link
        result = magic_link_service.consume_magic_link(
            db=db, token=token, ip_address="192.168.1.1", user_agent="Test Agent"
        )

        assert result.user.id == test_user.id
        assert result.access_token is not None
        assert result.refresh_token is not None
        assert result.session_id is not None

        # Check magic link was consumed
        db.refresh(magic_link)
        assert magic_link.is_consumed

    def test_consume_magic_link_expired(self, db: Session, test_user: User):
        """Test magic link consumption with expired token."""
        # Create expired magic link
        expired_time = datetime.now(timezone.utc) - timedelta(minutes=20)
        magic_link = MagicLink(
            email=test_user.email, nonce="test-nonce-expired", issued_at=expired_time
        )
        db.add(magic_link)
        db.commit()

        # Create expired token
        with patch.object(magic_link_service, "_verify_token") as mock_verify:
            from app.services.magic_link_service import SignatureExpired

            mock_verify.side_effect = SignatureExpired()

            with pytest.raises(MagicLinkError) as exc_info:
                magic_link_service.consume_magic_link(
                    db=db, token="expired-token", ip_address="192.168.1.1"
                )

            assert exc_info.value.code == "ERR-ML-EXPIRED"

    def test_consume_magic_link_already_used(self, db: Session, test_user: User):
        """Test magic link consumption when already used."""
        # Create consumed magic link
        magic_link = MagicLink(email=test_user.email, nonce="test-nonce-used")
        magic_link.consume()  # Mark as consumed
        db.add(magic_link)
        db.commit()

        # Create token
        token = magic_link_service._create_token(
            {
                "email": test_user.email,
                "nonce": "test-nonce-used",
                "iat": int(datetime.now(timezone.utc).timestamp()),
            }
        )

        with pytest.raises(MagicLinkError) as exc_info:
            magic_link_service.consume_magic_link(db=db, token=token, ip_address="192.168.1.1")

        assert exc_info.value.code == "ERR-ML-ALREADY-USED"

    def test_rate_limiting(self, db: Session, test_user: User):
        """Test rate limiting for magic link requests."""
        # Make maximum allowed requests
        for i in range(5):
            result = magic_link_service.request_magic_link(
                db=db, email=test_user.email, ip_address="192.168.1.1"
            )
            assert result is True

        # Next request should be rate limited
        with pytest.raises(MagicLinkError) as exc_info:
            magic_link_service.request_magic_link(
                db=db, email=test_user.email, ip_address="192.168.1.1"
            )

        assert exc_info.value.code == "ERR-ML-RATE-LIMITED"

    def test_cleanup_expired_links(self, db: Session):
        """Test cleanup of expired magic links."""
        # Create old magic links
        old_time = datetime.now(timezone.utc) - timedelta(hours=25)
        for i in range(3):
            magic_link = MagicLink(
                email=f"test{i}@example.com", nonce=f"old-nonce-{i}", issued_at=old_time
            )
            db.add(magic_link)

        # Create recent magic link
        recent_link = MagicLink(email="recent@example.com", nonce="recent-nonce")
        db.add(recent_link)
        db.commit()

        # Run cleanup
        cleanup_count = magic_link_service.cleanup_expired_links(db)

        assert cleanup_count == 3

        # Check recent link is still valid
        db.refresh(recent_link)
        assert recent_link.is_valid


class TestMagicLinkAPI:
    """Test magic link API endpoints."""

    def test_request_magic_link_endpoint(self, client: TestClient, test_user: User):
        """Test magic link request endpoint."""
        with patch.object(magic_link_service, "_send_magic_link_email"):
            response = client.post(
                "/api/v1/auth/magic-link/request",
                json={"email": test_user.email, "device_fingerprint": "fp_test123"},
            )

        assert response.status_code == 202
        data = response.json()
        assert "Magic link e-posta adresinize gönderildi" in data["message"]
        assert data["expires_in_minutes"] == 15

    def test_request_magic_link_nonexistent_user(self, client: TestClient):
        """Test magic link request for non-existent user (should still return 202)."""
        response = client.post(
            "/api/v1/auth/magic-link/request", json={"email": "nonexistent@example.com"}
        )

        assert response.status_code == 202  # Always success for security
        data = response.json()
        assert "Magic link e-posta adresinize gönderildi" in data["message"]

    def test_consume_magic_link_endpoint(self, client: TestClient, db: Session, test_user: User):
        """Test magic link consumption endpoint."""
        # Create magic link
        magic_link = MagicLink(email=test_user.email, nonce="test-nonce-api")
        db.add(magic_link)
        db.commit()

        # Create token
        token = magic_link_service._create_token(
            {
                "email": test_user.email,
                "nonce": "test-nonce-api",
                "iat": int(datetime.now(timezone.utc).timestamp()),
            }
        )

        response = client.post(
            "/api/v1/auth/magic-link/consume",
            json={"token": token, "device_fingerprint": "fp_test123"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] is not None
        assert data["user_id"] == test_user.id
        assert data["email"] == test_user.email
        assert data["login_method"] == "magic_link"

        # Check refresh token cookie is set
        assert "rt" in response.cookies

    def test_consume_invalid_magic_link(self, client: TestClient):
        """Test consumption of invalid magic link."""
        response = client.post("/api/v1/auth/magic-link/consume", json={"token": "invalid-token"})

        assert response.status_code == 401
        data = response.json()
        assert data["error_code"] == "ERR-ML-INVALID"
        assert "Magic link geçersiz" in data["message"]

    def test_magic_link_health_endpoint(self, client: TestClient):
        """Test magic link health check endpoint."""
        response = client.get("/api/v1/auth/magic-link/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "magic_link"

    def test_request_magic_link_validation(self, client: TestClient):
        """Test request validation for magic link endpoint."""
        # Invalid email
        response = client.post("/api/v1/auth/magic-link/request", json={"email": "invalid-email"})
        assert response.status_code == 422

        # Missing email
        response = client.post("/api/v1/auth/magic-link/request", json={})
        assert response.status_code == 422

    def test_consume_magic_link_validation(self, client: TestClient):
        """Test request validation for consume endpoint."""
        # Missing token
        response = client.post("/api/v1/auth/magic-link/consume", json={})
        assert response.status_code == 422

        # Token too short
        response = client.post("/api/v1/auth/magic-link/consume", json={"token": "short"})
        assert response.status_code == 422


class TestMagicLinkSecurity:
    """Test magic link security features."""

    def test_token_uniqueness(self, db: Session, test_user: User):
        """Test that magic link tokens are unique."""
        tokens = set()

        # Generate multiple tokens
        for i in range(10):
            magic_link = MagicLink(email=test_user.email, nonce=f"test-nonce-{i}")
            db.add(magic_link)
            db.commit()

            token = magic_link_service._create_token(
                {
                    "email": test_user.email,
                    "nonce": f"test-nonce-{i}",
                    "iat": int(datetime.now(timezone.utc).timestamp()),
                }
            )

            tokens.add(token)

        # All tokens should be unique
        assert len(tokens) == 10

    def test_audit_logging(self, db: Session, test_user: User):
        """Test that magic link operations are properly audited."""
        # Request magic link
        with patch.object(magic_link_service, "_send_magic_link_email"):
            magic_link_service.request_magic_link(
                db=db, email=test_user.email, ip_address="192.168.1.1"
            )

        # Check audit log
        audit_log = db.query(AuditLog).filter(AuditLog.action == "magic_link_requested").first()

        assert audit_log is not None
        assert audit_log.user_id == test_user.id
        assert "Magic link istendi" in audit_log.description

    def test_security_event_logging(self, db: Session):
        """Test security event logging for suspicious activity."""
        # Trigger rate limiting (security event)
        for i in range(6):  # Exceed rate limit
            try:
                magic_link_service.request_magic_link(
                    db=db, email="test@example.com", ip_address="192.168.1.1"
                )
            except MagicLinkError:
                pass

        # Check security event
        security_event = (
            db.query(SecurityEvent)
            .filter(SecurityEvent.event_type == "MAGIC_LINK_RATE_LIMITED")
            .first()
        )

        assert security_event is not None
        assert security_event.severity in ["HIGH", "MEDIUM"]

    def test_device_fingerprint_tracking(self, db: Session, test_user: User):
        """Test device fingerprint tracking in magic links."""
        # Create magic link with device fingerprint
        magic_link = MagicLink(
            email=test_user.email, nonce="test-fingerprint", device_fingerprint="fp_original123"
        )
        db.add(magic_link)
        db.commit()

        # Consume with different device fingerprint
        magic_link.consume(device_fingerprint="fp_different456")

        # Get security summary
        summary = magic_link.get_security_summary()
        assert summary["device_fingerprint_match"] is False


# Fixtures
@pytest.fixture
def test_user(db: Session) -> User:
    """Create a test user."""
    user = User(
        email="testuser@example.com",
        password_hash="hashed_password",
        full_name="Test User",
        data_processing_consent=True,
    )
    db.add(user)
    db.commit()
    return user
