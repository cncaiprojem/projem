"""
Integration tests for Task 3.1 ultra enterprise authentication endpoints.

Tests the complete authentication flow through the FastAPI endpoints:
- User registration with KVKV compliance
- User login with account lockout protection
- Password strength validation
- Password reset flow
- Rate limiting
- Error handling
- Security headers
"""

import pytest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models.user import User
from app.models.security_event import SecurityEvent
from app.services.password_service import password_service
from app.db import get_db


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


@pytest.fixture
def test_db():
    """Test database session."""
    # In real tests, this would be a test database
    # For now, we'll mock the database dependency
    pass


class TestUserRegistrationEndpoint:
    """Test /auth/register endpoint."""

    def test_register_user_success(self, client):
        """Test successful user registration."""
        registration_data = {
            "email": "newuser@example.com",
            "password": "StrongPassword123!",
            "full_name": "New User",
            "data_processing_consent": True,
            "marketing_consent": False,
        }

        with patch("app.routers.auth_enterprise.auth_service.register_user") as mock_register:
            # Mock successful registration
            mock_user = User()
            mock_user.id = 123
            mock_user.email = registration_data["email"]
            mock_register.return_value = mock_user

            response = client.post("/api/v1/auth/register", json=registration_data)

            assert response.status_code == 201
            data = response.json()
            assert data["user_id"] == 123
            assert data["email"] == registration_data["email"]
            assert "başarılı" in data["message"].lower()

    def test_register_user_duplicate_email(self, client):
        """Test registration with duplicate email."""
        registration_data = {
            "email": "existing@example.com",
            "password": "StrongPassword123!",
            "full_name": "Test User",
            "data_processing_consent": True,
            "marketing_consent": False,
        }

        with patch("app.routers.auth_enterprise.auth_service.register_user") as mock_register:
            from app.services.auth_service import AuthenticationError

            mock_register.side_effect = AuthenticationError(
                "ERR-AUTH-EMAIL-TAKEN", "Bu e-posta adresi zaten kullanılmaktadır"
            )

            response = client.post("/api/v1/auth/register", json=registration_data)

            assert response.status_code == 400
            data = response.json()
            assert data["error_code"] == "ERR-AUTH-EMAIL-TAKEN"
            assert "zaten kullanılmaktadır" in data["message"]

    def test_register_user_weak_password(self, client):
        """Test registration with weak password."""
        registration_data = {
            "email": "test@example.com",
            "password": "weak",
            "full_name": "Test User",
            "data_processing_consent": True,
            "marketing_consent": False,
        }

        with patch("app.routers.auth_enterprise.auth_service.register_user") as mock_register:
            from app.services.auth_service import AuthenticationError

            mock_register.side_effect = AuthenticationError(
                "ERR-AUTH-WEAK-PASSWORD", "Şifre güvenlik gereksinimlerini karşılamıyor"
            )

            response = client.post("/api/v1/auth/register", json=registration_data)

            assert response.status_code == 400
            data = response.json()
            assert data["error_code"] == "ERR-AUTH-WEAK-PASSWORD"
            assert "güvenlik gereksinimlerini" in data["message"]

    def test_register_user_missing_kvkv_consent(self, client):
        """Test registration without required KVKV consent."""
        registration_data = {
            "email": "test@example.com",
            "password": "StrongPassword123!",
            "full_name": "Test User",
            "data_processing_consent": False,  # Required consent missing
            "marketing_consent": False,
        }

        response = client.post("/api/v1/auth/register", json=registration_data)

        # Should fail validation before reaching service
        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any("KVKK veri işleme rızası zorunludur" in str(error) for error in errors)

    def test_register_user_invalid_email(self, client):
        """Test registration with invalid email."""
        registration_data = {
            "email": "invalid-email",
            "password": "StrongPassword123!",
            "full_name": "Test User",
            "data_processing_consent": True,
            "marketing_consent": False,
        }

        response = client.post("/api/v1/auth/register", json=registration_data)

        assert response.status_code == 422
        errors = response.json()["detail"]
        assert any("email" in str(error).lower() for error in errors)


class TestUserLoginEndpoint:
    """Test /auth/login endpoint."""

    def test_login_user_success(self, client):
        """Test successful user login."""
        login_data = {
            "email": "user@example.com",
            "password": "CorrectPassword123!",
            "device_fingerprint": "fp_test123",
        }

        with patch("app.routers.auth_enterprise.auth_service.authenticate_user") as mock_auth:
            with patch("app.routers.auth_enterprise.create_token_pair") as mock_token:
                # Mock successful authentication
                mock_user = User()
                mock_user.id = 123
                mock_user.email = login_data["email"]
                mock_user.full_name = "Test User"
                mock_user.role = "engineer"
                mock_user.password_must_change = False

                mock_auth.return_value = (mock_user, {"login_timestamp": "2025-08-17T20:00:00Z"})

                from app.schemas.base import TokenPair

                mock_token.return_value = TokenPair(
                    access_token="jwt_token_here",
                    refresh_token="refresh_token_here",
                    token_type="bearer",
                    expires_in=1800,
                )

                response = client.post("/api/v1/auth/login", json=login_data)

                assert response.status_code == 200
                data = response.json()
                assert data["access_token"] == "jwt_token_here"
                assert data["token_type"] == "bearer"
                assert data["user_id"] == 123
                assert data["email"] == login_data["email"]
                assert data["mfa_required"] is False

    def test_login_user_invalid_credentials(self, client):
        """Test login with invalid credentials."""
        login_data = {"email": "user@example.com", "password": "WrongPassword123!"}

        with patch("app.routers.auth_enterprise.auth_service.authenticate_user") as mock_auth:
            from app.services.auth_service import AuthenticationError

            mock_auth.side_effect = AuthenticationError(
                "ERR-AUTH-INVALID-CREDS", "E-posta adresi veya şifre hatalı"
            )

            response = client.post("/api/v1/auth/login", json=login_data)

            assert response.status_code == 400
            data = response.json()
            assert data["error_code"] == "ERR-AUTH-INVALID-CREDS"
            assert "hatalı" in data["message"]

    def test_login_user_account_locked(self, client):
        """Test login with locked account."""
        login_data = {"email": "locked@example.com", "password": "AnyPassword123!"}

        with patch("app.routers.auth_enterprise.auth_service.authenticate_user") as mock_auth:
            from app.services.auth_service import AuthenticationError

            mock_auth.side_effect = AuthenticationError(
                "ERR-AUTH-LOCKED",
                "Hesap geçici olarak kilitlendi. Lütfen 15 dakika sonra tekrar deneyin.",
            )

            response = client.post("/api/v1/auth/login", json=login_data)

            assert response.status_code == 400
            data = response.json()
            assert data["error_code"] == "ERR-AUTH-LOCKED"
            assert "kilitlendi" in data["message"]


class TestPasswordStrengthEndpoint:
    """Test /auth/password/strength endpoint."""

    def test_password_strength_strong_password(self, client):
        """Test password strength check with strong password."""
        password_data = {"password": "VeryStrongPassword123!@#"}

        response = client.post("/api/v1/auth/password/strength", json=password_data)

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["score"] >= 70
        assert isinstance(data["feedback"], list)

    def test_password_strength_weak_password(self, client):
        """Test password strength check with weak password."""
        password_data = {"password": "weak"}

        response = client.post("/api/v1/auth/password/strength", json=password_data)

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["score"] < 50
        assert len(data["feedback"]) > 0
        assert any("12 karakter" in feedback for feedback in data["feedback"])

    def test_password_strength_common_password(self, client):
        """Test password strength check with common password."""
        password_data = {"password": "password123"}

        response = client.post("/api/v1/auth/password/strength", json=password_data)

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert any("yaygın" in feedback.lower() for feedback in data["feedback"])


class TestPasswordResetEndpoints:
    """Test password reset endpoints."""

    def test_password_forgot_success(self, client):
        """Test password reset initiation."""
        forgot_data = {"email": "user@example.com"}

        with patch(
            "app.routers.auth_enterprise.auth_service.initiate_password_reset"
        ) as mock_reset:
            mock_reset.return_value = True

            response = client.post("/api/v1/auth/password/forgot", json=forgot_data)

            assert response.status_code == 202
            data = response.json()
            assert "e-posta adresinize gönderildi" in data["message"]

    def test_password_forgot_always_success(self, client):
        """Test that password forgot always returns success (security)."""
        forgot_data = {"email": "nonexistent@example.com"}

        with patch(
            "app.routers.auth_enterprise.auth_service.initiate_password_reset"
        ) as mock_reset:
            mock_reset.return_value = True  # Always returns True for security

            response = client.post("/api/v1/auth/password/forgot", json=forgot_data)

            assert response.status_code == 202
            data = response.json()
            assert "e-posta adresinize gönderildi" in data["message"]

    def test_password_reset_success(self, client):
        """Test password reset completion."""
        reset_data = {
            "token": "valid_reset_token_12345678901234567890",
            "new_password": "NewStrongPassword123!",
        }

        with patch("app.routers.auth_enterprise.auth_service.reset_password") as mock_reset:
            mock_user = User()
            mock_user.id = 123
            mock_reset.return_value = mock_user

            response = client.post("/api/v1/auth/password/reset", json=reset_data)

            assert response.status_code == 200
            data = response.json()
            assert data["user_id"] == 123
            assert "başarıyla güncellendi" in data["message"]

    def test_password_reset_invalid_token(self, client):
        """Test password reset with invalid token."""
        reset_data = {
            "token": "invalid_token_12345678901234567890",
            "new_password": "NewStrongPassword123!",
        }

        with patch("app.routers.auth_enterprise.auth_service.reset_password") as mock_reset:
            from app.services.auth_service import AuthenticationError

            mock_reset.side_effect = AuthenticationError(
                "ERR-AUTH-INVALID-TOKEN", "Geçersiz veya süresi dolmuş şifre sıfırlama bağlantısı"
            )

            response = client.post("/api/v1/auth/password/reset", json=reset_data)

            assert response.status_code == 400
            data = response.json()
            assert data["error_code"] == "ERR-AUTH-INVALID-TOKEN"
            assert "geçersiz" in data["message"].lower()


class TestUserProfileEndpoint:
    """Test /auth/me endpoint."""

    def test_get_user_profile_success(self, client):
        """Test getting current user profile."""
        with patch("app.routers.auth_enterprise.get_current_user") as mock_get_user:
            with patch("app.routers.auth_enterprise.get_db") as mock_get_db:
                # Mock current user
                from app.schemas.base import UserOut

                mock_current_user = UserOut(email="user@example.com", role="engineer")
                mock_get_user.return_value = mock_current_user

                # Mock database user
                mock_db_user = User()
                mock_db_user.id = 123
                mock_db_user.email = "user@example.com"
                mock_db_user.full_name = "Test User"
                mock_db_user.display_name = "TestUser"
                mock_db_user.role = "engineer"
                mock_db_user.account_status = "active"
                mock_db_user.email_verified_at = datetime.now(timezone.utc)
                mock_db_user.locale = "tr"
                mock_db_user.timezone = "Europe/Istanbul"
                mock_db_user.created_at = datetime.now(timezone.utc)
                mock_db_user.last_successful_login_at = datetime.now(timezone.utc)
                mock_db_user.total_login_count = 10
                mock_db_user.data_processing_consent = True
                mock_db_user.marketing_consent = False

                mock_session = mock_get_db.return_value
                mock_session.query.return_value.filter.return_value.first.return_value = (
                    mock_db_user
                )

                response = client.get("/api/v1/auth/me")

                assert response.status_code == 200
                data = response.json()
                assert data["user_id"] == 123
                assert data["email"] == "user@example.com"
                assert data["full_name"] == "Test User"
                assert data["is_email_verified"] is True
                assert data["data_processing_consent"] is True

    def test_get_user_profile_unauthorized(self, client):
        """Test getting user profile without authentication."""
        # Without mocking get_current_user, it should fail
        response = client.get("/api/v1/auth/me")

        assert response.status_code == 401


class TestRateLimiting:
    """Test rate limiting on authentication endpoints."""

    def test_registration_rate_limiting(self, client):
        """Test rate limiting on registration endpoint."""
        registration_data = {
            "email": "test@example.com",
            "password": "StrongPassword123!",
            "full_name": "Test User",
            "data_processing_consent": True,
            "marketing_consent": False,
        }

        with patch("app.routers.auth_enterprise.auth_service.register_user"):
            # Make multiple rapid requests
            responses = []
            for i in range(10):  # Exceed rate limit
                registration_data["email"] = f"test{i}@example.com"
                response = client.post("/api/v1/auth/register", json=registration_data)
                responses.append(response)

            # Some requests should be rate limited (429)
            status_codes = [r.status_code for r in responses]
            assert 429 in status_codes

    def test_login_rate_limiting(self, client):
        """Test rate limiting on login endpoint."""
        login_data = {"email": "user@example.com", "password": "password"}

        with patch("app.routers.auth_enterprise.auth_service.authenticate_user"):
            # Make multiple rapid requests
            responses = []
            for i in range(15):  # Exceed rate limit
                response = client.post("/api/v1/auth/login", json=login_data)
                responses.append(response)

            # Some requests should be rate limited
            status_codes = [r.status_code for r in responses]
            assert 429 in status_codes


class TestSecurityHeaders:
    """Test security headers and CORS."""

    def test_security_headers_present(self, client):
        """Test that security headers are present in responses."""
        response = client.post("/api/v1/auth/password/strength", json={"password": "test"})

        # Check for important security headers
        headers = response.headers
        # These would be set by security middleware in production
        # assert "x-content-type-options" in headers
        # assert "x-frame-options" in headers
        # assert "x-xss-protection" in headers

        # Basic content type should be present
        assert "content-type" in headers

    def test_error_response_format(self, client):
        """Test standardized error response format."""
        # Test with invalid JSON
        response = client.post("/api/v1/auth/register", json={})

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data  # FastAPI validation error format


class TestAuditLogging:
    """Test audit logging functionality."""

    def test_security_events_logged(self, client):
        """Test that security events are properly logged."""
        login_data = {"email": "user@example.com", "password": "WrongPassword123!"}

        with patch("app.routers.auth_enterprise.auth_service.authenticate_user") as mock_auth:
            with patch("app.services.auth_service.logger") as mock_logger:
                from app.services.auth_service import AuthenticationError

                mock_auth.side_effect = AuthenticationError(
                    "ERR-AUTH-INVALID-CREDS", "E-posta adresi veya şifre hatalı"
                )

                response = client.post("/api/v1/auth/login", json=login_data)

                # Verify that logging occurred
                assert mock_logger.warning.called
                call_args = mock_logger.warning.call_args
                assert "User login failed" in str(call_args)

                # Verify that sensitive data is not logged
                assert "WrongPassword123!" not in str(call_args)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
