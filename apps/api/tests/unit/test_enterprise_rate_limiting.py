"""
Comprehensive Tests for Ultra Enterprise Rate Limiting (Task 3.9)

This test suite validates the enterprise rate limiting implementation including:
- Redis-backed rate limiting with fastapi-limiter
- Per-route policy enforcement
- IP + user composite keying
- Security event logging and brute force detection
- Turkish localized error responses
- X-Forwarded-For header handling
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any

from fastapi import Request, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.rate_limiting_service import (
    EnterpriseRateLimitingService,
    RateLimitType,
    RateLimitResult,
    RateLimitPolicy,
)
from app.middleware.enterprise_rate_limiter import RateLimitDependency
from app.middleware.jwt_middleware import AuthenticatedUser
from app.models.security_event import SecurityEvent
from app.models.user import User


class TestEnterpriseRateLimitingService:
    """Test suite for the enterprise rate limiting service."""

    @pytest.fixture
    def mock_redis_client(self):
        """Mock Redis client for testing."""
        mock_redis = Mock()
        mock_redis.pipeline.return_value.__enter__.return_value.execute.return_value = [
            None,
            1,
            None,
            None,
        ]
        return mock_redis

    @pytest.fixture
    def rate_service(self, mock_redis_client):
        """Create rate limiting service with mocked Redis."""
        service = EnterpriseRateLimitingService()
        service.redis_client = mock_redis_client
        return service

    @pytest.fixture
    def mock_request(self):
        """Create mock FastAPI request."""
        request = Mock(spec=Request)
        request.client.host = "192.168.1.100"
        request.headers = {
            "user-agent": "Mozilla/5.0 Test Browser",
            "x-forwarded-for": "203.0.113.1, 192.168.1.100",
        }
        request.url.path = "/api/v1/auth/login"
        return request

    @pytest.fixture
    def mock_user(self):
        """Create mock authenticated user."""
        user = Mock(spec=AuthenticatedUser)
        user.user_id = 123
        user.session_id = "session_456"
        return user

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = Mock(spec=Session)
        return db

    def test_get_client_ip_direct_connection(self, rate_service, mock_request):
        """Test IP extraction from direct connection."""
        mock_request.headers = {}
        result = rate_service.get_client_ip(mock_request, trust_proxy=False)
        assert result == "192.168.1.100"

    def test_get_client_ip_x_forwarded_for(self, rate_service, mock_request):
        """Test IP extraction from X-Forwarded-For header."""
        result = rate_service.get_client_ip(mock_request, trust_proxy=True)
        assert result == "203.0.113.1"  # First IP in chain

    def test_get_client_ip_x_real_ip(self, rate_service, mock_request):
        """Test IP extraction from X-Real-IP header."""
        mock_request.headers = {"x-real-ip": "198.51.100.1"}
        result = rate_service.get_client_ip(mock_request, trust_proxy=True)
        assert result == "198.51.100.1"

    def test_get_client_ip_invalid_format(self, rate_service, mock_request):
        """Test handling of invalid IP address format."""
        mock_request.headers = {"x-forwarded-for": "invalid-ip-address"}
        result = rate_service.get_client_ip(mock_request, trust_proxy=True)
        assert result is None

    def test_generate_rate_limit_key_ip_only(self, rate_service, mock_request):
        """Test rate limit key generation for IP-only policy."""
        key = rate_service.generate_rate_limit_key(
            mock_request, RateLimitType.REGISTRATION, user=None
        )
        assert key == "registration:ip:203.0.113.1"

    def test_generate_rate_limit_key_user_only(self, rate_service, mock_request, mock_user):
        """Test rate limit key generation for user-only policy."""
        key = rate_service.generate_rate_limit_key(
            mock_request, RateLimitType.AI_PROMPT, user=mock_user
        )
        assert key == "ai_prompt:user:123"

    def test_generate_rate_limit_key_ip_user_composite(self, rate_service, mock_request, mock_user):
        """Test rate limit key generation for IP+user composite policy."""
        key = rate_service.generate_rate_limit_key(
            mock_request, RateLimitType.LOGIN, user=mock_user
        )
        assert key == "login:ip_user:203.0.113.1:123"

    def test_generate_rate_limit_key_session_based(self, rate_service, mock_request, mock_user):
        """Test rate limit key generation for session-based policy."""
        key = rate_service.generate_rate_limit_key(
            mock_request, RateLimitType.TOKEN_REFRESH, user=mock_user, session_id="session_456"
        )
        assert key == "token_refresh:session:session_456"

    @pytest.mark.asyncio
    async def test_check_rate_limit_allowed(self, rate_service, mock_request, mock_user, mock_db):
        """Test rate limit check when request is allowed."""
        # Mock Redis to return low count
        rate_service.redis_client.pipeline.return_value.__enter__.return_value.execute.return_value = [
            None,
            2,
            None,
            None,
        ]

        result = await rate_service.check_rate_limit(
            mock_request, RateLimitType.LOGIN, mock_db, user=mock_user
        )

        assert result.allowed is True
        assert result.remaining == 2  # 5 - 3 (2 + new request)
        assert result.limit == 5
        assert result.policy_type == RateLimitType.LOGIN

    @pytest.mark.asyncio
    async def test_check_rate_limit_exceeded(self, rate_service, mock_request, mock_user, mock_db):
        """Test rate limit check when limit is exceeded."""
        # Mock Redis to return high count
        rate_service.redis_client.pipeline.return_value.__enter__.return_value.execute.return_value = [
            None,
            5,
            None,
            None,
        ]

        with patch.object(rate_service, "_check_brute_force_pattern") as mock_brute_force:
            with patch.object(rate_service, "_log_rate_limit_event") as mock_log_event:
                result = await rate_service.check_rate_limit(
                    mock_request, RateLimitType.LOGIN, mock_db, user=mock_user
                )

        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after > 0
        mock_brute_force.assert_called_once()
        mock_log_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_brute_force_detection(self, rate_service, mock_request, mock_user, mock_db):
        """Test brute force attack detection."""
        # Mock high request count exceeding burst threshold
        current_count = 15  # Exceeds burst threshold of 10

        await rate_service._check_brute_force_pattern(
            mock_request, RateLimitType.LOGIN, mock_db, mock_user, current_count
        )

        # Verify security event was created
        mock_db.add.assert_called_once()
        security_event = mock_db.add.call_args[0][0]
        assert isinstance(security_event, SecurityEvent)
        assert security_event.event_type == "potential_bruteforce_detected"
        assert security_event.severity == "high"
        assert security_event.details["request_count"] == 15
        assert security_event.details["burst_threshold"] == 10

    @pytest.mark.asyncio
    async def test_rate_limit_event_logging(self, rate_service, mock_request, mock_user, mock_db):
        """Test security event logging for rate limit violations."""
        request_count = 8  # Exceeds limit of 5

        await rate_service._log_rate_limit_event(
            mock_request, RateLimitType.LOGIN, mock_db, mock_user, request_count
        )

        # Verify security event was created
        mock_db.add.assert_called_once()
        security_event = mock_db.add.call_args[0][0]
        assert isinstance(security_event, SecurityEvent)
        assert security_event.event_type == "rate_limited"
        assert security_event.severity == "medium"
        assert security_event.details["request_count"] == 8
        assert security_event.details["limit"] == 5
        assert security_event.resolved is True  # Auto-resolved

    def test_create_rate_limit_exception_turkish_localization(self, rate_service):
        """Test rate limit exception creation with Turkish localization."""
        result = RateLimitResult(
            allowed=False,
            remaining=0,
            reset_time=int(time.time()) + 60,
            retry_after=60,
            limit=5,
            window=60,
            key="test_key",
            policy_type=RateLimitType.LOGIN,
        )

        exception = rate_service.create_rate_limit_exception(result, RateLimitType.LOGIN)

        assert exception.status_code == 429
        assert "ERR-RATE-LIMIT" in exception.detail["error_code"]
        assert "giriş denemesi" in exception.detail["message"]  # Turkish text
        assert "60 saniye sonra" in exception.detail["message"]  # Turkish text
        assert exception.headers["Retry-After"] == "60"
        assert exception.headers["X-RateLimit-Limit"] == "5"
        assert exception.headers["X-RateLimit-Policy"] == "login"

    def test_policy_configurations(self, rate_service):
        """Test that all required policies are properly configured."""
        policies = rate_service.POLICIES

        # Verify Task 3.9 requirements
        assert policies[RateLimitType.LOGIN].requests == 5
        assert policies[RateLimitType.LOGIN].window_seconds == 60

        assert policies[RateLimitType.MAGIC_LINK_REQUEST].requests == 3
        assert policies[RateLimitType.MAGIC_LINK_REQUEST].window_seconds == 60

        assert policies[RateLimitType.TOKEN_REFRESH].requests == 60
        assert policies[RateLimitType.TOKEN_REFRESH].window_seconds == 60

        assert policies[RateLimitType.AI_PROMPT].requests == 30
        assert policies[RateLimitType.AI_PROMPT].window_seconds == 60

        # Verify all policies have burst thresholds for brute force detection
        for policy_type, policy in policies.items():
            if policy_type != RateLimitType.GENERAL:
                assert policy.burst_threshold is not None
                assert policy.burst_threshold > policy.requests


class TestRateLimitDependency:
    """Test suite for FastAPI rate limit dependency."""

    @pytest.fixture
    def mock_rate_service(self):
        """Mock rate limiting service."""
        service = Mock(spec=EnterpriseRateLimitingService)
        return service

    @pytest.fixture
    def rate_limit_dependency(self):
        """Create rate limit dependency for testing."""
        return RateLimitDependency(RateLimitType.LOGIN)

    @pytest.mark.asyncio
    async def test_dependency_allowed_request(
        self, rate_limit_dependency, mock_request, mock_db, mock_rate_service
    ):
        """Test dependency when request is allowed."""
        # Mock allowed rate limit result
        mock_result = RateLimitResult(
            allowed=True,
            remaining=3,
            reset_time=int(time.time()) + 60,
            retry_after=0,
            limit=5,
            window=60,
            key="test_key",
            policy_type=RateLimitType.LOGIN,
        )
        mock_rate_service.check_rate_limit.return_value = mock_result

        # Should not raise exception
        result = await rate_limit_dependency(
            mock_request, mock_db, current_user=None, rate_service=mock_rate_service
        )
        assert result is None  # No exception raised

    @pytest.mark.asyncio
    async def test_dependency_blocked_request(
        self, rate_limit_dependency, mock_request, mock_db, mock_rate_service
    ):
        """Test dependency when request is blocked."""
        # Mock blocked rate limit result
        mock_result = RateLimitResult(
            allowed=False,
            remaining=0,
            reset_time=int(time.time()) + 60,
            retry_after=60,
            limit=5,
            window=60,
            key="test_key",
            policy_type=RateLimitType.LOGIN,
        )
        mock_rate_service.check_rate_limit.return_value = mock_result
        mock_rate_service.create_rate_limit_exception.return_value = HTTPException(
            status_code=429,
            detail={"error_code": "ERR-RATE-LIMIT", "message": "Rate limit exceeded"},
        )

        # Should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await rate_limit_dependency(
                mock_request, mock_db, current_user=None, rate_service=mock_rate_service
            )

        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_dependency_service_failure(
        self, rate_limit_dependency, mock_request, mock_db, mock_rate_service
    ):
        """Test dependency when rate limiting service fails."""
        # Mock service failure
        mock_rate_service.check_rate_limit.side_effect = Exception("Redis connection failed")

        # Should not raise exception (fail-open behavior)
        result = await rate_limit_dependency(
            mock_request, mock_db, current_user=None, rate_service=mock_rate_service
        )
        assert result is None


class TestRateLimitPolicyEnforcement:
    """Integration tests for rate limit policy enforcement."""

    def test_login_endpoint_rate_limiting(self):
        """Test that login endpoint has correct rate limiting applied."""
        # This would be tested with actual TestClient in integration tests
        # For now, verify the dependency is correctly configured
        from app.routers.auth_enterprise import login_user
        import inspect

        # Check that rate limit dependency is in function signature
        sig = inspect.signature(login_user)
        assert "_rate_limit_check" in sig.parameters

    def test_magic_link_endpoint_rate_limiting(self):
        """Test that magic link endpoint has correct rate limiting applied."""
        from app.routers.magic_link_auth import request_magic_link
        import inspect

        # Check that rate limit dependency is in function signature
        sig = inspect.signature(request_magic_link)
        assert "_rate_limit_check" in sig.parameters

    def test_token_refresh_endpoint_rate_limiting(self):
        """Test that token refresh endpoint has correct rate limiting applied."""
        from app.routers.auth_jwt import refresh_access_token
        import inspect

        # Check that rate limit dependency is in function signature
        sig = inspect.signature(refresh_access_token)
        assert "_rate_limit_check" in sig.parameters


class TestRedisConfiguration:
    """Test Redis configuration and connection management."""

    @pytest.mark.asyncio
    async def test_redis_connection_initialization(self):
        """Test Redis connection initialization."""
        from app.core.redis_config import redis_manager

        # Mock Redis client
        with patch("app.core.redis_config.redis.Redis") as mock_redis_class:
            mock_client = Mock()
            mock_client.ping.return_value = True
            mock_redis_class.return_value = mock_client

            client = redis_manager.get_redis_client()
            assert client is not None
            mock_client.ping.assert_called_once()

    def test_redis_health_check(self):
        """Test Redis health check functionality."""
        from app.core.redis_config import redis_manager

        # Mock healthy Redis
        with patch.object(redis_manager, "get_redis_client") as mock_get_client:
            mock_client = Mock()
            mock_client.ping.return_value = True
            mock_get_client.return_value = mock_client

            result = redis_manager.health_check()
            assert result is True

        # Mock unhealthy Redis
        with patch.object(redis_manager, "get_redis_client") as mock_get_client:
            mock_client = Mock()
            mock_client.ping.side_effect = Exception("Connection failed")
            mock_get_client.return_value = mock_client

            result = redis_manager.health_check()
            assert result is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
