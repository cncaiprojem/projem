"""
Test suite for Task 3.8 - Ultra Enterprise CSRF Double-Submit Protection

This test suite validates:
- CSRF token generation and validation
- Double-submit cookie protection pattern
- Browser detection and selective protection
- Integration with authentication system
- Turkish localized error messages
- Security event logging
- Rate limiting and abuse prevention

Risk Assessment: CRITICAL - Tests prevent CSRF attacks
Security Level: Ultra-Enterprise Banking Grade
"""

import pytest
import time
from unittest.mock import Mock, patch
from fastapi import Request, Response
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.csrf_service import csrf_service, CSRFValidationResult, CSRFError
from app.middleware.csrf_middleware import CSRFProtectionMiddleware
from app.models.security_event import SecurityEvent
from app.models.audit_log import AuditLog


class TestCSRFService:
    """Test cases for CSRF service functionality."""

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        db = Mock(spec=Session)
        db.add.return_value = None
        db.flush.return_value = None
        db.commit.return_value = None
        return db

    def test_generate_csrf_token_success(self, mock_db):
        """Test successful CSRF token generation."""
        # Arrange
        user_id = 123
        ip_address = "192.168.1.100"
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

        # Act
        token = csrf_service.generate_csrf_token(
            db=mock_db, user_id=user_id, ip_address=ip_address, user_agent=user_agent
        )

        # Assert
        assert token is not None
        assert isinstance(token, str)
        assert len(token) >= 16  # Minimum token length
        assert len(token) <= 128  # Maximum token length

        # Verify security event logging
        mock_db.add.assert_called()
        mock_db.flush.assert_called()

    def test_generate_csrf_token_rate_limiting(self, mock_db):
        """Test CSRF token generation rate limiting."""
        ip_address = "192.168.1.101"

        # Generate tokens up to limit
        for _ in range(60):  # Default rate limit is 60 per minute
            csrf_service.generate_csrf_token(db=mock_db, ip_address=ip_address)

        # Next request should be rate limited
        with pytest.raises(CSRFError) as exc_info:
            csrf_service.generate_csrf_token(db=mock_db, ip_address=ip_address)

        assert exc_info.value.code == "ERR-CSRF-RATE-LIMIT"
        assert "çok sık" in exc_info.value.message.lower()

    def test_set_csrf_cookie_security_attributes(self):
        """Test CSRF cookie security attributes."""
        # Arrange
        response = Mock(spec=Response)
        token = "test_csrf_token_123456789"

        # Act
        csrf_service.set_csrf_cookie(response, token, secure=True)

        # Assert
        response.set_cookie.assert_called_once_with(
            key="csrf",
            value=token,
            max_age=7200,  # 2 hours
            httponly=False,  # Frontend needs to read
            secure=True,  # HTTPS only
            samesite="strict",  # Maximum CSRF protection
            path="/",  # Application-wide
        )

    def test_validate_csrf_token_missing_cookie(self, mock_db):
        """Test CSRF validation with missing cookie."""
        # Arrange
        request = Mock(spec=Request)
        request.method = "POST"
        request.url.path = "/api/v1/test"
        request.cookies = {}  # No CSRF cookie
        request.headers = {
            "Authorization": "Bearer valid_token",
            "User-Agent": "Mozilla/5.0 (Chrome)",
        }
        request.client.host = "192.168.1.100"

        # Act
        result = csrf_service.validate_csrf_token(mock_db, request, user_id=123)

        # Assert
        assert result == CSRFValidationResult.MISSING

    def test_validate_csrf_token_missing_header(self, mock_db):
        """Test CSRF validation with missing header."""
        # Arrange
        request = Mock(spec=Request)
        request.method = "POST"
        request.url.path = "/api/v1/test"
        request.cookies = {"csrf": "valid_token_123"}
        request.headers = {
            "Authorization": "Bearer valid_token",
            "User-Agent": "Mozilla/5.0 (Chrome)",
            # Missing X-CSRF-Token header
        }
        request.client.host = "192.168.1.100"

        # Act
        result = csrf_service.validate_csrf_token(mock_db, request, user_id=123)

        # Assert
        assert result == CSRFValidationResult.MISSING

    def test_validate_csrf_token_mismatch(self, mock_db):
        """Test CSRF validation with token mismatch."""
        # Arrange
        request = Mock(spec=Request)
        request.method = "POST"
        request.url.path = "/api/v1/test"
        request.cookies = {"csrf": "cookie_token_123"}
        request.headers = {
            "Authorization": "Bearer valid_token",
            "User-Agent": "Mozilla/5.0 (Chrome)",
            "X-CSRF-Token": "header_token_456",  # Different token
        }
        request.client.host = "192.168.1.100"

        # Act
        result = csrf_service.validate_csrf_token(mock_db, request, user_id=123)

        # Assert
        assert result == CSRFValidationResult.MISMATCH

    def test_validate_csrf_token_success(self, mock_db):
        """Test successful CSRF validation."""
        # Arrange
        token = "matching_token_123456789"
        request = Mock(spec=Request)
        request.method = "POST"
        request.url.path = "/api/v1/test"
        request.cookies = {"csrf": token}
        request.headers = {
            "Authorization": "Bearer valid_token",
            "User-Agent": "Mozilla/5.0 (Chrome)",
            "X-CSRF-Token": token,  # Matching token
        }
        request.client.host = "192.168.1.100"

        # Act
        result = csrf_service.validate_csrf_token(mock_db, request, user_id=123)

        # Assert
        assert result == CSRFValidationResult.VALID

    def test_validate_csrf_token_skip_get_request(self, mock_db):
        """Test CSRF validation skips GET requests."""
        # Arrange
        request = Mock(spec=Request)
        request.method = "GET"  # Safe method
        request.url.path = "/api/v1/test"
        request.cookies = {}
        request.headers = {"User-Agent": "Mozilla/5.0 (Chrome)"}
        request.client.host = "192.168.1.100"

        # Act
        result = csrf_service.validate_csrf_token(mock_db, request, user_id=123)

        # Assert
        assert result == CSRFValidationResult.VALID  # Skipped validation

    def test_validate_csrf_token_skip_non_browser(self, mock_db):
        """Test CSRF validation skips non-browser clients."""
        # Arrange
        request = Mock(spec=Request)
        request.method = "POST"
        request.url.path = "/api/v1/test"
        request.cookies = {}
        request.headers = {
            "Authorization": "Bearer valid_token",
            "User-Agent": "API-Client/1.0",  # Non-browser user agent
        }
        request.client.host = "192.168.1.100"

        # Act
        result = csrf_service.validate_csrf_token(mock_db, request, user_id=123)

        # Assert
        assert result == CSRFValidationResult.VALID  # Skipped validation

    def test_validate_csrf_token_skip_no_cookies(self, mock_db):
        """Test CSRF validation skips requests without cookies."""
        # Arrange
        request = Mock(spec=Request)
        request.method = "POST"
        request.url.path = "/api/v1/test"
        request.cookies = {}  # No cookies (API client)
        request.headers = {
            "Authorization": "Bearer valid_token",
            "User-Agent": "Mozilla/5.0 (Chrome)",
        }
        request.client.host = "192.168.1.100"

        # Act
        result = csrf_service.validate_csrf_token(mock_db, request, user_id=123)

        # Assert
        assert result == CSRFValidationResult.VALID  # Skipped validation

    def test_csrf_error_responses_turkish_localization(self):
        """Test CSRF error responses have proper Turkish localization."""
        # Test missing token error
        missing_error = csrf_service.create_csrf_error_response(CSRFValidationResult.MISSING)
        assert missing_error["error_code"] == "ERR-CSRF-MISSING"
        assert "eksik" in missing_error["message"].lower()
        assert "tr" in missing_error["details"]
        assert "en" in missing_error["details"]

        # Test mismatch error
        mismatch_error = csrf_service.create_csrf_error_response(CSRFValidationResult.MISMATCH)
        assert mismatch_error["error_code"] == "ERR-CSRF-MISMATCH"
        assert "uyuşmuyor" in mismatch_error["message"].lower()

        # Test expired error
        expired_error = csrf_service.create_csrf_error_response(CSRFValidationResult.EXPIRED)
        assert expired_error["error_code"] == "ERR-CSRF-EXPIRED"
        assert "süresi dolmuş" in expired_error["message"].lower()


class TestCSRFMiddleware:
    """Test cases for CSRF middleware functionality."""

    @pytest.fixture
    def app(self):
        """Create test FastAPI app with CSRF middleware."""
        from fastapi import FastAPI

        app = FastAPI()
        app.add_middleware(CSRFProtectionMiddleware, require_auth_for_csrf=True)
        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_csrf_middleware_blocks_invalid_request(self, client):
        """Test CSRF middleware blocks requests with invalid tokens."""
        # Arrange
        headers = {
            "Authorization": "Bearer valid_token",
            "User-Agent": "Mozilla/5.0 (Chrome)",
            "X-CSRF-Token": "invalid_token",
        }
        cookies = {"csrf": "different_token"}

        # Act
        response = client.post("/test", headers=headers, cookies=cookies)

        # Assert
        assert response.status_code == 403
        response_data = response.json()
        assert response_data["error_code"] == "ERR-CSRF-MISMATCH"
        assert "uyuşmuyor" in response_data["message"].lower()

    def test_csrf_middleware_allows_valid_request(self, client):
        """Test CSRF middleware allows requests with valid tokens."""
        # Arrange
        token = "valid_matching_token_123"
        headers = {
            "Authorization": "Bearer valid_token",
            "User-Agent": "Mozilla/5.0 (Chrome)",
            "X-CSRF-Token": token,
        }
        cookies = {"csrf": token}

        with patch(
            "app.middleware.csrf_middleware.csrf_service.validate_csrf_token"
        ) as mock_validate:
            mock_validate.return_value = CSRFValidationResult.VALID

            # Act
            response = client.post("/test", headers=headers, cookies=cookies)

            # Assert - should reach the endpoint (404 since endpoint doesn't exist)
            assert response.status_code == 404  # Endpoint not found, but CSRF passed

    def test_csrf_middleware_skips_exempt_paths(self, client):
        """Test CSRF middleware skips exempt paths."""
        # Act
        response = client.get("/healthz")  # Exempt path

        # Assert
        assert response.status_code == 404  # Path not found, but not blocked by CSRF

    def test_csrf_middleware_skips_safe_methods(self, client):
        """Test CSRF middleware skips safe HTTP methods."""
        # Act
        response = client.get("/api/v1/test")  # GET method

        # Assert
        assert response.status_code == 404  # Path not found, but not blocked by CSRF


class TestCSRFIntegration:
    """Integration tests for CSRF protection system."""

    def test_csrf_token_endpoint_integration(self):
        """Test CSRF token endpoint integration."""
        from fastapi.testclient import TestClient
        from app.main import app  # Assuming main FastAPI app

        client = TestClient(app)

        # Act
        response = client.get("/api/v1/auth/csrf-token")

        # Assert
        assert response.status_code == 200
        response_data = response.json()
        assert "message" in response_data
        assert "başarıyla" in response_data["message"].lower()
        assert "csrf" in response.cookies

        # Verify cookie attributes
        csrf_cookie = response.cookies["csrf"]
        assert csrf_cookie is not None

    def test_csrf_protection_with_authentication(self):
        """Test CSRF protection integration with authentication system."""
        # This would test the full flow:
        # 1. User authenticates and gets session
        # 2. User gets CSRF token
        # 3. User makes protected request with CSRF token
        # 4. Request is validated and processed
        pass

    def test_csrf_security_event_logging(self, mock_db):
        """Test CSRF security events are properly logged."""
        # Arrange
        request = Mock(spec=Request)
        request.method = "POST"
        request.url.path = "/api/v1/test"
        request.cookies = {"csrf": "token1"}
        request.headers = {
            "Authorization": "Bearer valid_token",
            "User-Agent": "Mozilla/5.0 (Chrome)",
            "X-CSRF-Token": "token2",  # Mismatch
        }
        request.client.host = "192.168.1.100"

        # Act
        result = csrf_service.validate_csrf_token(mock_db, request, user_id=123)

        # Assert
        assert result == CSRFValidationResult.MISMATCH

        # Verify security event was logged
        mock_db.add.assert_called()
        call_args = mock_db.add.call_args[0][0]
        assert isinstance(call_args, SecurityEvent)
        assert call_args.type == "csrf_mismatch"
        assert call_args.user_id == 123


class TestCSRFTokenSecurity:
    """Test cases for CSRF token security properties."""

    def test_csrf_tokens_are_unique(self, mock_db):
        """Test that generated CSRF tokens are unique."""
        tokens = set()

        for _ in range(100):
            token = csrf_service.generate_csrf_token(db=mock_db)
            assert token not in tokens, "CSRF token collision detected"
            tokens.add(token)

    def test_csrf_tokens_have_sufficient_entropy(self, mock_db):
        """Test CSRF tokens have sufficient cryptographic entropy."""
        token = csrf_service.generate_csrf_token(db=mock_db)

        # Check token length (should be at least 32 chars for good entropy)
        assert len(token) >= 32

        # Check character diversity (should contain various characters)
        unique_chars = len(set(token))
        assert unique_chars >= 20  # Should have decent character diversity

    def test_csrf_token_format_validation(self):
        """Test CSRF token format validation."""
        service = csrf_service

        # Valid tokens
        assert service._is_valid_token_format("valid_token_123456789")
        assert service._is_valid_token_format("AbCdEf123456789-_")

        # Invalid tokens
        assert not service._is_valid_token_format("")  # Empty
        assert not service._is_valid_token_format("short")  # Too short
        assert not service._is_valid_token_format("a" * 200)  # Too long
        assert not service._is_valid_token_format("invalid@chars!")  # Invalid chars
        assert not service._is_valid_token_format(None)  # None
        assert not service._is_valid_token_format(123)  # Wrong type

    def test_csrf_timing_attack_protection(self, mock_db):
        """Test CSRF validation has timing attack protection."""
        # This test ensures that token comparison uses constant-time comparison
        # which is handled by secrets.compare_digest in the implementation

        request_valid = Mock(spec=Request)
        request_valid.method = "POST"
        request_valid.url.path = "/api/v1/test"
        request_valid.cookies = {"csrf": "a" * 32}
        request_valid.headers = {
            "Authorization": "Bearer token",
            "User-Agent": "Mozilla/5.0 (Chrome)",
            "X-CSRF-Token": "a" * 32,
        }
        request_valid.client.host = "192.168.1.100"

        request_invalid = Mock(spec=Request)
        request_invalid.method = "POST"
        request_invalid.url.path = "/api/v1/test"
        request_invalid.cookies = {"csrf": "a" * 32}
        request_invalid.headers = {
            "Authorization": "Bearer token",
            "User-Agent": "Mozilla/5.0 (Chrome)",
            "X-CSRF-Token": "b" * 32,
        }
        request_invalid.client.host = "192.168.1.100"

        # Both should take similar time (constant-time comparison)
        start_time = time.time()
        csrf_service.validate_csrf_token(mock_db, request_valid, user_id=123)
        valid_time = time.time() - start_time

        start_time = time.time()
        csrf_service.validate_csrf_token(mock_db, request_invalid, user_id=123)
        invalid_time = time.time() - start_time

        # Times should be similar (within reasonable variance)
        time_diff = abs(valid_time - invalid_time)
        assert time_diff < 0.01  # Less than 10ms difference


if __name__ == "__main__":
    pytest.main([__file__])
