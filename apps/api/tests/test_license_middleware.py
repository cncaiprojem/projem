"""
Tests for Task 4.3: License Guard Middleware
Tests license enforcement, session revocation, and error handling.
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock
from fastapi import Request, Response
from fastapi.responses import JSONResponse

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.middleware.license_middleware import (
    LicenseGuardMiddleware,
    get_current_user_from_request,
    clear_license_expiry_cache,
    is_user_license_expiry_processed
)
from app.models.license import License
from app.models.session import Session  
from app.models.user import User
from app.middleware.jwt_middleware import AuthenticatedUser


class TestLicenseGuardMiddleware:
    """Test suite for License Guard Middleware."""
    
    def setup_method(self):
        """Set up test environment before each test."""
        clear_license_expiry_cache()
    
    @pytest.fixture
    def middleware(self):
        """Create middleware instance for testing."""
        return LicenseGuardMiddleware(app=Mock())
    
    @pytest.fixture
    def mock_request(self):
        """Create mock request object."""
        request = Mock(spec=Request)
        request.url.path = "/api/v1/jobs"
        request.client.host = "192.168.1.100"
        request.headers = {"user-agent": "TestClient/1.0"}
        return request
    
    @pytest.fixture
    def mock_user(self):
        """Create mock user object."""
        user = Mock(spec=User)
        user.id = 123
        user.email = "test@example.com"
        user.is_active = True
        return user
    
    @pytest.fixture
    def mock_session(self):
        """Create mock session object."""
        session = Mock(spec=Session)
        session.id = uuid.uuid4()
        session.user_id = 123
        session.revoked_at = None
        return session
    
    @pytest.fixture
    def mock_license_active(self):
        """Create mock active license."""
        license = Mock(spec=License)
        license.id = uuid.uuid4()
        license.user_id = 123
        license.type = "12m"
        license.status = "active"
        license.starts_at = datetime.now(timezone.utc) - timedelta(days=30)
        license.ends_at = datetime.now(timezone.utc) + timedelta(days=335)
        return license
    
    @pytest.fixture
    def mock_license_expired(self):
        """Create mock expired license."""
        license = Mock(spec=License)
        license.id = uuid.uuid4()
        license.user_id = 123
        license.type = "12m"
        license.status = "active"
        license.starts_at = datetime.now(timezone.utc) - timedelta(days=400)
        license.ends_at = datetime.now(timezone.utc) - timedelta(days=30)
        return license
    
    def test_middleware_initialization(self, middleware):
        """Test middleware initializes with correct excluded paths."""
        expected_paths = [
            "/api/v1/auth",
            "/api/v1/health",
            "/webhooks",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/",
            "/api/v1/license/me"
        ]
        assert middleware.excluded_paths == expected_paths
    
    def test_is_path_excluded(self, middleware):
        """Test path exclusion logic."""
        # Test excluded paths
        assert middleware._is_path_excluded("/api/v1/auth/login") is True
        assert middleware._is_path_excluded("/api/v1/health") is True
        assert middleware._is_path_excluded("/webhooks/stripe") is True
        assert middleware._is_path_excluded("/docs") is True
        assert middleware._is_path_excluded("/api/v1/license/me") is True
        
        # Test protected paths
        assert middleware._is_path_excluded("/api/v1/jobs") is False
        assert middleware._is_path_excluded("/api/v1/designs") is False
        assert middleware._is_path_excluded("/api/v1/license/assign") is False
    
    def test_anonymize_ip(self, middleware):
        """Test IP address anonymization for KVKV compliance."""
        # IPv4 addresses
        assert middleware._anonymize_ip("192.168.1.100") == "192.168.1.xxx"
        assert middleware._anonymize_ip("10.0.0.1") == "10.0.0.xxx"
        
        # IPv6 addresses
        assert middleware._anonymize_ip("2001:db8:85a3:0:0:8a2e:370:7334") == "2001:db8:85a3::xxxx"
        
        # Edge cases
        assert middleware._anonymize_ip("unknown") == "unknown"
        assert middleware._anonymize_ip("") == ""
        assert middleware._anonymize_ip("invalid") == "invalid"
    
    def test_get_client_info(self, middleware, mock_request):
        """Test client information extraction."""
        client_ip, user_agent = middleware._get_client_info(mock_request)
        
        assert client_ip == "192.168.1.xxx"  # Anonymized
        assert user_agent == "TestClient/1.0"
    
    @pytest.mark.asyncio
    async def test_get_current_user_from_request_no_header(self):
        """Test user extraction with no authorization header."""
        mock_request = Mock(spec=Request)
        mock_request.headers = {}
        
        user_id = await get_current_user_from_request(mock_request)
        assert user_id is None
    
    @pytest.mark.asyncio
    async def test_get_current_user_from_request_invalid_header(self):
        """Test user extraction with invalid authorization header."""
        mock_request = Mock(spec=Request)
        mock_request.headers = {"authorization": "Basic dGVzdA=="}
        
        user_id = await get_current_user_from_request(mock_request)
        assert user_id is None
    
    @pytest.mark.asyncio
    @patch('app.middleware.license_middleware._authenticate_user')
    @patch('app.middleware.license_middleware.get_db')
    async def test_get_current_user_from_request_valid_token(self, mock_get_db, mock_auth_user):
        """Test user extraction with valid token."""
        # Setup mocks
        mock_db = Mock()
        mock_get_db.return_value = iter([mock_db])
        
        mock_authenticated_user = Mock(spec=AuthenticatedUser)
        mock_authenticated_user.user_id = 123
        mock_auth_user.return_value = mock_authenticated_user
        
        mock_request = Mock(spec=Request)
        mock_request.headers = {"authorization": "Bearer valid_token_here"}
        
        user_id = await get_current_user_from_request(mock_request)
        assert user_id == 123
        mock_auth_user.assert_called_once_with("valid_token_here", mock_db)
    
    @pytest.mark.asyncio
    @patch('app.middleware.license_middleware.LicenseService.get_active_license')
    @patch('app.middleware.license_middleware.get_db')
    async def test_check_license_valid(self, mock_get_db, mock_get_license, middleware, mock_request, mock_license_active):
        """Test license check with valid license."""
        # Setup mocks
        mock_db = Mock()
        mock_get_db.return_value = iter([mock_db])
        mock_get_license.return_value = mock_license_active
        
        result = await middleware._check_license_and_enforce(mock_request, 123, "test-request-id")
        
        assert result is None  # No error response means license is valid
        mock_get_license.assert_called_once_with(mock_db, 123)
    
    @pytest.mark.asyncio
    @patch('app.middleware.license_middleware.LicenseService.get_active_license')
    @patch('app.middleware.license_middleware.get_db')
    async def test_check_license_no_license(self, mock_get_db, mock_get_license, middleware, mock_request):
        """Test license check with no active license."""
        # Setup mocks
        mock_db = Mock()
        mock_get_db.return_value = iter([mock_db])
        mock_get_license.return_value = None
        
        result = await middleware._check_license_and_enforce(mock_request, 123, "test-request-id")
        
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403
        
        # Check response content
        content = result.body.decode()
        assert "LIC_EXPIRED" in content
        assert "no_active_license" in content
    
    @pytest.mark.asyncio
    @patch('app.middleware.license_middleware.LicenseService.get_active_license')
    @patch('app.middleware.license_middleware.get_db')
    async def test_check_license_expired(self, mock_get_db, mock_get_license, middleware, mock_request, mock_license_expired):
        """Test license check with expired license."""
        # Setup mocks
        mock_db = Mock()
        mock_get_db.return_value = iter([mock_db])
        mock_get_license.return_value = mock_license_expired
        
        with patch.object(middleware, '_revoke_user_sessions_on_expiry', return_value=True) as mock_revoke:
            result = await middleware._check_license_and_enforce(mock_request, 123, "test-request-id")
            
            assert isinstance(result, JSONResponse)
            assert result.status_code == 403
            
            # Check response content
            content = result.body.decode()
            assert "LIC_EXPIRED" in content
            assert "license_expired" in content
            
            # Verify session revocation was called
            mock_revoke.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('app.middleware.license_middleware.session_service.revoke_all_user_sessions')
    @patch('app.middleware.license_middleware.audit_service.log_business_event')
    async def test_revoke_user_sessions_on_expiry(self, mock_audit, mock_revoke_sessions, middleware, mock_request):
        """Test session revocation on license expiry."""
        # Setup mocks
        mock_db = Mock()
        mock_revoke_sessions.return_value = 3  # 3 sessions revoked
        mock_audit.return_value = AsyncMock()
        
        result = await middleware._revoke_user_sessions_on_expiry(
            mock_db, 123, "192.168.1.xxx", "TestClient/1.0", "test-request-id"
        )
        
        assert result is True
        mock_revoke_sessions.assert_called_once_with(
            db=mock_db,
            user_id=123,
            reason="license_expired",
            ip_address="192.168.1.xxx",
            user_agent="TestClient/1.0"
        )
        
        # Verify audit event was logged
        mock_audit.assert_called_once()
        audit_call = mock_audit.call_args
        assert audit_call[1]['event_type'] == "sessions_revoked_license_expired"
        assert audit_call[1]['details']['revoked_sessions_count'] == 3
    
    @pytest.mark.asyncio
    async def test_revoke_user_sessions_thread_safety(self, middleware, mock_request):
        """Test thread-safe session revocation (no double processing)."""
        mock_db = Mock()
        
        # First call should process
        with patch('app.middleware.license_middleware.session_service.revoke_all_user_sessions', return_value=2):
            with patch('app.middleware.license_middleware.audit_service.log_business_event', return_value=AsyncMock()):
                result1 = await middleware._revoke_user_sessions_on_expiry(
                    mock_db, 123, "192.168.1.xxx", "TestClient/1.0", "test-request-id-1"
                )
        
        assert result1 is True
        assert is_user_license_expiry_processed(123) is True
        
        # Second call should skip processing
        result2 = await middleware._revoke_user_sessions_on_expiry(
            mock_db, 123, "192.168.1.xxx", "TestClient/1.0", "test-request-id-2"
        )
        
        assert result2 is True
    
    @pytest.mark.asyncio
    @patch('app.middleware.license_middleware.get_current_user_from_request')
    async def test_dispatch_excluded_path(self, mock_get_user, middleware):
        """Test middleware dispatch for excluded paths."""
        mock_call_next = AsyncMock(return_value=Response())
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/api/v1/health"
        
        result = await middleware.dispatch(mock_request, mock_call_next)
        
        # Should call next without checking user or license
        mock_call_next.assert_called_once_with(mock_request)
        mock_get_user.assert_not_called()
    
    @pytest.mark.asyncio
    @patch('app.middleware.license_middleware.get_current_user_from_request')
    async def test_dispatch_no_user(self, mock_get_user, middleware):
        """Test middleware dispatch when no user is authenticated."""
        mock_call_next = AsyncMock(return_value=Response())
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/api/v1/jobs"
        mock_get_user.return_value = None
        
        result = await middleware.dispatch(mock_request, mock_call_next)
        
        # Should call next without license check
        mock_call_next.assert_called_once_with(mock_request)
        mock_get_user.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('app.middleware.license_middleware.get_current_user_from_request')
    async def test_dispatch_valid_license(self, mock_get_user, middleware):
        """Test middleware dispatch with valid license."""
        mock_call_next = AsyncMock(return_value=Response())
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/api/v1/jobs"
        mock_get_user.return_value = 123
        
        with patch.object(middleware, '_check_license_and_enforce', return_value=None) as mock_check:
            result = await middleware.dispatch(mock_request, mock_call_next)
            
            # Should call next after successful license check
            mock_call_next.assert_called_once_with(mock_request)
            mock_check.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('app.middleware.license_middleware.get_current_user_from_request')
    async def test_dispatch_invalid_license(self, mock_get_user, middleware):
        """Test middleware dispatch with invalid license."""
        mock_call_next = AsyncMock()
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/api/v1/jobs"
        mock_get_user.return_value = 123
        
        error_response = JSONResponse(status_code=403, content={"error": "LIC_EXPIRED"})
        
        with patch.object(middleware, '_check_license_and_enforce', return_value=error_response) as mock_check:
            result = await middleware.dispatch(mock_request, mock_call_next)
            
            # Should return error response without calling next
            assert result == error_response
            mock_call_next.assert_not_called()
    
    @pytest.mark.asyncio
    @patch('app.middleware.license_middleware.get_current_user_from_request')
    async def test_dispatch_unexpected_error(self, mock_get_user, middleware):
        """Test middleware dispatch with unexpected error."""
        mock_call_next = AsyncMock()
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/api/v1/jobs"
        mock_get_user.side_effect = Exception("Unexpected error")
        
        result = await middleware.dispatch(mock_request, mock_call_next)
        
        # Should return 403 error response due to fail-closed policy
        assert isinstance(result, JSONResponse)
        assert result.status_code == 403
        
        content = result.body.decode()
        assert "LIC_EXPIRED" in content
        assert "service_unavailable" in content
    
    def test_clear_license_expiry_cache(self):
        """Test license expiry cache clearing."""
        # Add some users to processed set
        from app.middleware.license_middleware import _license_expiry_processed
        _license_expiry_processed.add(123)
        _license_expiry_processed.add(456)
        
        assert is_user_license_expiry_processed(123) is True
        assert is_user_license_expiry_processed(456) is True
        
        clear_license_expiry_cache()
        
        assert is_user_license_expiry_processed(123) is False
        assert is_user_license_expiry_processed(456) is False


class TestLicenseMiddlewareIntegration:
    """Integration tests for license middleware."""
    
    @pytest.mark.asyncio
    async def test_full_flow_expired_license(self):
        """Test complete flow for expired license scenario."""
        # This would be an integration test with real database
        # For now, just verify the test structure is in place
        pass
    
    @pytest.mark.asyncio 
    async def test_performance_license_check(self):
        """Test performance of license check under load."""
        # Performance test to ensure middleware doesn't introduce significant latency
        pass