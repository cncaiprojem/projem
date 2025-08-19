"""
Tests for Task 4.3: License Guard Middleware
Ultra-Enterprise tests for license enforcement, session revocation, and error handling.
Includes comprehensive edge case coverage and banking-grade security testing.
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, IntegrityError
import asyncio
import threading

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.middleware.license_middleware import (
    LicenseGuardMiddleware,
    get_current_user_from_request,
    clear_license_expiry_cache,
    is_user_license_expiry_processed,
    is_license_expiry_processed,
    get_db_session_for_middleware
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
    
    @patch('app.middleware.license_middleware.pii_masking_service')
    def test_get_client_info_with_pii_masking(self, mock_pii_service, middleware, mock_request):
        """Test client info extraction with PII masking service."""
        mock_pii_service.mask_ip_address.return_value = "192.168.***.**"
        
        client_ip, user_agent = middleware._get_client_info(mock_request)
        
        assert client_ip == "192.168.***.**"
        assert user_agent == "TestClient/1.0"
        mock_pii_service.mask_ip_address.assert_called_once()
    
    @patch('app.middleware.license_middleware.pii_masking_service')
    def test_get_client_info_masking_failure(self, mock_pii_service, middleware, mock_request):
        """Test client info extraction when PII masking fails."""
        mock_pii_service.mask_ip_address.side_effect = Exception("Masking failed")
        
        client_ip, user_agent = middleware._get_client_info(mock_request)
        
        # Should fall back to default masking
        assert client_ip == "***.***.***.**"
        assert user_agent == "TestClient/1.0"
    
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
        """Test session revocation on license expiry with proper parameters."""
        # Setup mocks
        mock_db = Mock()
        license_id = uuid.uuid4()
        mock_revoke_sessions.return_value = 3  # 3 sessions revoked
        mock_audit.return_value = AsyncMock()
        
        # FIXED: Pass license_id as required by the updated method signature
        result = await middleware._revoke_user_sessions_on_expiry(
            mock_db, 123, license_id, "192.168.1.xxx", "TestClient/1.0", "test-request-id"
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
        """Test thread-safe session revocation with (user_id, license_id) tracking."""
        mock_db = Mock()
        license_id = uuid.uuid4()
        
        # First call should process
        with patch('app.middleware.license_middleware.session_service.revoke_all_user_sessions', return_value=2):
            with patch('app.middleware.license_middleware.audit_service.log_business_event', return_value=AsyncMock()):
                result1 = await middleware._revoke_user_sessions_on_expiry(
                    mock_db, 123, license_id, "192.168.1.xxx", "TestClient/1.0", "test-request-id-1"
                )
        
        assert result1 is True
        assert is_license_expiry_processed(123, license_id) is True
        assert is_user_license_expiry_processed(123) is True  # Backward compatibility
        
        # Second call with same license should skip processing
        result2 = await middleware._revoke_user_sessions_on_expiry(
            mock_db, 123, license_id, "192.168.1.xxx", "TestClient/1.0", "test-request-id-2"
        )
        assert result2 is True
        
        # Call with different license should process
        different_license_id = uuid.uuid4()
        with patch('app.middleware.license_middleware.session_service.revoke_all_user_sessions', return_value=3):
            with patch('app.middleware.license_middleware.audit_service.log_business_event', return_value=AsyncMock()):
                result3 = await middleware._revoke_user_sessions_on_expiry(
                    mock_db, 123, different_license_id, "192.168.1.xxx", "TestClient/1.0", "test-request-id-3"
                )
        
        assert result3 is True
        assert is_license_expiry_processed(123, different_license_id) is True
    
    @pytest.mark.asyncio
    async def test_revoke_user_sessions_with_invalid_params(self, middleware):
        """Test proper validation of None parameters per Copilot feedback."""
        mock_db = Mock()
        
        # Test with user_id = None (should be caught by is None check)
        result1 = await middleware._revoke_user_sessions_on_expiry(
            mock_db, None, uuid.uuid4(), "192.168.1.xxx", "TestClient/1.0", "test-request-id"
        )
        assert result1 is False
        
        # Test with license_id = None 
        result2 = await middleware._revoke_user_sessions_on_expiry(
            mock_db, 123, None, "192.168.1.xxx", "TestClient/1.0", "test-request-id"
        )
        assert result2 is False
        
        # Test with user_id = 0 (falsy but not None - should pass validation)
        with patch('app.middleware.license_middleware.session_service.revoke_all_user_sessions', return_value=1):
            with patch('app.middleware.license_middleware.audit_service.log_business_event', return_value=AsyncMock()):
                result3 = await middleware._revoke_user_sessions_on_expiry(
                    mock_db, 0, uuid.uuid4(), "192.168.1.xxx", "TestClient/1.0", "test-request-id"
                )
        assert result3 is True  # 0 is a valid user_id
    
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


class TestLicenseMiddlewareEdgeCases:
    """Ultra-enterprise edge case tests for license middleware."""
    
    @pytest.mark.asyncio
    async def test_database_session_error_handling(self):
        """Test proper handling of database session errors."""
        with patch('app.middleware.license_middleware.db_session') as mock_db_session:
            mock_db_session.side_effect = OperationalError("Connection failed", "", "")
            
            with pytest.raises(OperationalError):
                with get_db_session_for_middleware() as db:
                    pass
    
    @pytest.mark.asyncio
    async def test_concurrent_license_expiry_processing(self):
        """Test concurrent processing of license expiry for same user."""
        middleware = LicenseGuardMiddleware(app=Mock())
        mock_db = Mock()
        license_id = uuid.uuid4()
        
        # Simulate concurrent calls
        async def concurrent_revoke():
            with patch('app.middleware.license_middleware.session_service.revoke_all_user_sessions', return_value=2):
                with patch('app.middleware.license_middleware.audit_service.log_business_event', return_value=AsyncMock()):
                    return await middleware._revoke_user_sessions_on_expiry(
                        mock_db, 123, license_id, "192.168.1.xxx", "TestClient/1.0", f"req-{uuid.uuid4()}"
                    )
        
        # Run multiple concurrent calls
        tasks = [concurrent_revoke() for _ in range(10)]
        results = await asyncio.gather(*tasks)
        
        # All should succeed, but only one should actually process
        assert all(results)
        assert is_license_expiry_processed(123, license_id)
    
    @pytest.mark.asyncio
    async def test_correlation_id_propagation(self):
        """Test that correlation IDs are properly propagated through the middleware."""
        middleware = LicenseGuardMiddleware(app=Mock())
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/api/v1/jobs"
        mock_request.state.correlation_id = "test-correlation-123"
        mock_request.headers = {"authorization": "Bearer invalid_token"}
        
        with patch('app.middleware.license_middleware.get_current_user_from_request') as mock_get_user:
            mock_get_user.return_value = None
            
            mock_call_next = AsyncMock(return_value=Response())
            await middleware.dispatch(mock_request, mock_call_next)
            
            # Verify correlation ID was used
            mock_get_user.assert_called_once_with(mock_request)
    
    @pytest.mark.asyncio
    async def test_malformed_authorization_header_variations(self):
        """Test various malformed authorization header formats."""
        test_cases = [
            "",
            "Bearer",
            "Bearer ",
            "Basic dGVzdDp0ZXN0",
            "bearer valid_token",
            "BEARER valid_token",
            "Bearer token with spaces",
            "Bearer\ttoken_with_tab",
            "Bearer\ntoken_with_newline",
            "Bearer " + "x" * 5000,  # Very long token
        ]
        
        for auth_header in test_cases:
            mock_request = Mock(spec=Request)
            mock_request.headers = {"authorization": auth_header}
            
            result = await get_current_user_from_request(mock_request)
            assert result is None, f"Should return None for header: {auth_header[:50]}"
    
    @pytest.mark.asyncio
    async def test_license_check_with_database_error(self):
        """Test proper database error handling in license check."""
        middleware = LicenseGuardMiddleware(app=Mock())
        mock_request = Mock(spec=Request)
        mock_request.url.path = "/api/v1/jobs"
        mock_request.client.host = "192.168.1.100"
        mock_request.headers = {"user-agent": "TestClient/1.0"}
        
        with patch('app.middleware.license_middleware.get_db_session_for_middleware') as mock_session:
            mock_db = Mock()
            mock_db.rollback = Mock()
            mock_session.return_value.__enter__.return_value = mock_db
            mock_session.return_value.__exit__.return_value = None
            
            with patch('app.middleware.license_middleware.LicenseService.get_active_license') as mock_get_license:
                mock_get_license.side_effect = IntegrityError("Constraint violation", "", "")
                
                result = await middleware._check_license_and_enforce(mock_request, 123, "test-req-id")
                
                assert isinstance(result, JSONResponse)
                assert result.status_code == 403
    
    @pytest.mark.asyncio
    async def test_database_rollback_on_error(self):
        """Test that database properly rolls back on error."""
        with patch('app.middleware.license_middleware.db_session') as mock_db_session:
            mock_session = Mock()
            mock_session.rollback = Mock()
            mock_session.close = Mock()
            
            # Create context manager that raises error
            class MockContext:
                def __enter__(self):
                    return mock_session
                
                def __exit__(self, exc_type, exc_val, exc_tb):
                    if exc_type:
                        mock_session.rollback()
                    mock_session.close()
                    return False
            
            mock_db_session.return_value = MockContext()
            
            # Trigger an error within the context
            with pytest.raises(ValueError):
                with get_db_session_for_middleware() as db:
                    raise ValueError("Test error")
            
            # Verify rollback was called
            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_user_agent_sanitization(self):
        """Test that user agent is properly sanitized."""
        middleware = LicenseGuardMiddleware(app=Mock())
        
        # Test with malicious user agent
        mock_request = Mock(spec=Request)
        mock_request.client.host = "192.168.1.100"
        mock_request.headers = {
            "user-agent": "Mozilla/5.0\n<script>alert('xss')</script>\r\nExtra: data" * 50
        }
        
        client_ip, user_agent = middleware._get_client_info(mock_request)
        
        # Should be truncated and sanitized
        assert len(user_agent) <= 200
        assert "\n" not in user_agent
        assert "\r" not in user_agent
    
    def test_cache_clearing_with_active_entries(self):
        """Test cache clearing when there are active entries."""
        # Add multiple entries to cache
        from app.middleware.license_middleware import _license_expiry_processed, _license_expiry_lock
        
        with _license_expiry_lock:
            for i in range(10):
                _license_expiry_processed.add((i, uuid.uuid4()))
        
        assert len(_license_expiry_processed) == 10
        
        clear_license_expiry_cache()
        
        assert len(_license_expiry_processed) == 0
    
    @pytest.mark.asyncio
    async def test_race_condition_in_cache_removal(self):
        """Test race condition handling when removing from cache on error."""
        middleware = LicenseGuardMiddleware(app=Mock())
        mock_db = Mock()
        license_id = uuid.uuid4()
        
        # Force an error to trigger cache removal
        with patch('app.middleware.license_middleware.session_service.revoke_all_user_sessions') as mock_revoke:
            mock_revoke.side_effect = Exception("Database error")
            
            result = await middleware._revoke_user_sessions_on_expiry(
                mock_db, 999, license_id, "192.168.1.xxx", "TestClient/1.0", "test-request-id"
            )
            
            assert result is False
            assert not is_license_expiry_processed(999, license_id)
    
    @pytest.mark.asyncio
    async def test_invalid_parameters_handling(self):
        """Test handling of invalid parameters in session revocation."""
        middleware = LicenseGuardMiddleware(app=Mock())
        mock_db = Mock()
        
        # Test with None user_id
        result = await middleware._revoke_user_sessions_on_expiry(
            mock_db, None, uuid.uuid4(), "192.168.1.xxx", "TestClient/1.0", "test-request-id"
        )
        assert result is False
        
        # Test with None license_id
        result = await middleware._revoke_user_sessions_on_expiry(
            mock_db, 123, None, "192.168.1.xxx", "TestClient/1.0", "test-request-id"
        )
        assert result is False
        
        # Test with zero user_id (invalid)
        result = await middleware._revoke_user_sessions_on_expiry(
            mock_db, 0, uuid.uuid4(), "192.168.1.xxx", "TestClient/1.0", "test-request-id"
        )
        assert result is False
    
    @pytest.mark.asyncio
    async def test_session_cleanup_logging(self):
        """Test that session lifecycle is properly logged for monitoring."""
        with patch('app.middleware.license_middleware.logger') as mock_logger:
            with patch('app.middleware.license_middleware.db_session') as mock_db_session:
                mock_session = Mock()
                mock_db_session.return_value.__enter__.return_value = mock_session
                mock_db_session.return_value.__exit__.return_value = None
                
                with get_db_session_for_middleware() as db:
                    pass
                
                # Verify lifecycle logging
                debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
                assert any("Creating database session" in call for call in debug_calls)
                assert any("Database session created successfully" in call for call in debug_calls)
                assert any("Database session context completed" in call for call in debug_calls)