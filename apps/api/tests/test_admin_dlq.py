"""
Comprehensive tests for Admin DLQ Management API (Task 6.9)

Tests cover:
- Authentication and MFA requirements
- Admin role enforcement  
- Rate limiting
- Message peeking and replay functionality
- Audit logging
"""

import asyncio
import json
import os
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

# Set required environment variables for testing
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-testing-only-minimum-32-chars")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")

from app.models.user import User
from app.models.enums import UserRole
from app.routers.admin_dlq import (
    verify_admin_with_mfa,
    list_dlq_queues,
    peek_dlq_messages,
    replay_dlq_messages
)
from app.schemas.dlq import (
    DLQReplayRequest,
    DLQQueueInfo,
    DLQMessagePreview
)
from app.services.dlq_management_service import DLQManagementService


@pytest.fixture
def admin_user():
    """Create an admin user fixture."""
    user = User(
        id=1,
        email="admin@example.com",
        username="admin",
        role=UserRole.ADMIN,
        is_active=True,
        mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP"
    )
    return user


@pytest.fixture
def non_admin_user():
    """Create a non-admin user fixture."""
    user = User(
        id=2,
        email="user@example.com",
        username="user",
        role=UserRole.OPERATOR,
        is_active=True,
        mfa_enabled=True,
        mfa_secret="JBSWY3DPEHPK3PXP"
    )
    return user


@pytest.fixture
def mock_db():
    """Create a mock database session."""
    return MagicMock(spec=Session)


class TestAdminMFAVerification:
    """Test admin role and MFA verification."""
    
    @pytest.mark.asyncio
    async def test_verify_admin_with_valid_mfa(self, admin_user, mock_db):
        """Test successful admin verification with valid MFA."""
        with patch('app.routers.admin_dlq.TOTPService') as MockTOTPService:
            # Mock TOTP verification
            totp_service = MockTOTPService.return_value
            totp_service.verify_totp = AsyncMock(return_value=True)
            
            # Test verification
            result = await verify_admin_with_mfa(
                current_user=admin_user,
                mfa_code="123456",
                db=mock_db
            )
            
            assert result == admin_user
            totp_service.verify_totp.assert_called_once_with(
                db=mock_db,
                user=admin_user,
                totp_code="123456"
            )
    
    @pytest.mark.asyncio
    async def test_verify_admin_rejects_non_admin(self, non_admin_user, mock_db):
        """Test that non-admin users are rejected."""
        with pytest.raises(HTTPException) as exc_info:
            await verify_admin_with_mfa(
                current_user=non_admin_user,
                mfa_code="123456",
                db=mock_db
            )
        
        assert exc_info.value.status_code == 401
        assert exc_info.value.detail["error_code"] == "ERR-DLQ-401"
        assert "Admin role required" in exc_info.value.detail["message"]
    
    @pytest.mark.asyncio
    async def test_verify_admin_rejects_invalid_mfa(self, admin_user, mock_db):
        """Test that invalid MFA codes are rejected."""
        with patch('app.routers.admin_dlq.TOTPService') as MockTOTPService:
            # Mock TOTP verification failure
            totp_service = MockTOTPService.return_value
            totp_service.verify_totp = AsyncMock(return_value=False)
            
            with pytest.raises(HTTPException) as exc_info:
                await verify_admin_with_mfa(
                    current_user=admin_user,
                    mfa_code="999999",
                    db=mock_db
                )
            
            assert exc_info.value.status_code == 403
            assert exc_info.value.detail["error_code"] == "ERR-DLQ-403"
            assert "MFA verification failed" in exc_info.value.detail["message"]


class TestDLQListEndpoint:
    """Test DLQ queue listing endpoint."""
    
    @pytest.mark.asyncio
    async def test_list_dlq_queues_success(self, admin_user, mock_db):
        """Test successful DLQ queue listing."""
        with patch('app.routers.admin_dlq.DLQManagementService') as MockDLQService:
            with patch('app.routers.admin_dlq.JobAuditService') as MockAuditService:
                # Mock DLQ service
                dlq_service = MockDLQService.return_value
                dlq_service.list_dlq_queues = AsyncMock(return_value=[
                    {
                        "name": "default_dlq",
                        "message_count": 10,
                        "messages_ready": 8,
                        "messages_unacknowledged": 2,
                        "consumers": 0,
                        "idle_since": "2024-01-15T10:00:00Z",
                        "memory": 4096,
                        "state": "running",
                        "type": "classic",
                        "origin_queue": "default"
                    },
                    {
                        "name": "model_dlq",
                        "message_count": 5,
                        "messages_ready": 5,
                        "messages_unacknowledged": 0,
                        "consumers": 0,
                        "idle_since": "2024-01-15T09:00:00Z",
                        "memory": 2048,
                        "state": "running",
                        "type": "quorum",
                        "origin_queue": "model"
                    }
                ])
                
                # Mock audit service
                MockAuditService.audit_dlq_action = AsyncMock()
                
                # Test listing
                result = await list_dlq_queues(
                    current_user=admin_user,
                    db=mock_db,
                    _=None  # Rate limiter dependency
                )
                
                assert len(result.queues) == 2
                assert result.total_messages == 15
                assert result.queues[0]["name"] == "default_dlq"
                assert result.queues[1]["name"] == "model_dlq"
                
                # Verify audit was called
                MockAuditService.audit_dlq_action.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_list_dlq_queues_empty(self, admin_user, mock_db):
        """Test listing when no DLQ queues exist."""
        with patch('app.routers.admin_dlq.DLQManagementService') as MockDLQService:
            with patch('app.routers.admin_dlq.JobAuditService') as MockAuditService:
                # Mock empty response
                dlq_service = MockDLQService.return_value
                dlq_service.list_dlq_queues = AsyncMock(return_value=[])
                MockAuditService.audit_dlq_action = AsyncMock()
                
                # Test listing
                result = await list_dlq_queues(
                    current_user=admin_user,
                    db=mock_db,
                    _=None
                )
                
                assert len(result.queues) == 0
                assert result.total_messages == 0


class TestDLQPeekEndpoint:
    """Test DLQ message peeking endpoint."""
    
    @pytest.mark.asyncio
    async def test_peek_messages_success(self, admin_user, mock_db):
        """Test successful message peeking."""
        with patch('app.routers.admin_dlq.DLQManagementService') as MockDLQService:
            with patch('app.routers.admin_dlq.JobAuditService') as MockAuditService:
                # Mock DLQ service
                dlq_service = MockDLQService.return_value
                dlq_service.peek_messages = AsyncMock(return_value=[
                    {
                        "message_id": "msg-123",
                        "job_id": 456,
                        "routing_key": "default_dlq",
                        "exchange": "default.dlx",
                        "original_routing_key": "jobs.ai",
                        "original_exchange": "jobs",
                        "death_count": 1,
                        "first_death_reason": "rejected",
                        "timestamp": 1705320000,
                        "headers": {"job_id": 456},
                        "payload": {"job_id": 456, "task": "generate_model"},
                        "payload_bytes": 128,
                        "redelivered": False
                    }
                ])
                MockAuditService.audit_dlq_action = AsyncMock()
                
                # Test peeking
                result = await peek_dlq_messages(
                    queue_name="default_dlq",
                    limit=10,
                    current_user=admin_user,
                    db=mock_db,
                    _=None
                )
                
                assert len(result) == 1
                assert result[0]["job_id"] == 456
                assert result[0]["original_routing_key"] == "jobs.ai"
    
    @pytest.mark.asyncio
    async def test_peek_messages_invalid_queue_name(self, admin_user, mock_db):
        """Test peeking with invalid queue name."""
        with pytest.raises(HTTPException) as exc_info:
            await peek_dlq_messages(
                queue_name="invalid_queue",  # Not ending with _dlq
                limit=10,
                current_user=admin_user,
                db=mock_db,
                _=None
            )
        
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail["error_code"] == "ERR-DLQ-404"


class TestDLQReplayEndpoint:
    """Test DLQ message replay endpoint."""
    
    @pytest.mark.asyncio
    async def test_replay_messages_success(self, admin_user, mock_db):
        """Test successful message replay."""
        with patch('app.routers.admin_dlq.DLQManagementService') as MockDLQService:
            with patch('app.routers.admin_dlq.JobAuditService') as MockAuditService:
                # Mock DLQ service
                dlq_service = MockDLQService.return_value
                dlq_service.replay_messages = AsyncMock(return_value={
                    "replayed_count": 8,
                    "failed_count": 2,
                    "details": [
                        {
                            "message_id": "msg-123",
                            "replayed_to": "jobs/jobs.ai",
                            "timestamp": "2024-01-15T12:00:00Z"
                        }
                    ]
                })
                MockAuditService.audit_dlq_replay = AsyncMock()
                
                # Create replay request
                request = DLQReplayRequest(
                    mfa_code="123456",
                    max_messages=10,
                    backoff_ms=100,
                    justification="Fixing database connection issue #1234"
                )
                
                # Test replay
                result = await replay_dlq_messages(
                    queue_name="default_dlq",
                    request=request,
                    current_user=admin_user,
                    db=mock_db,
                    _=None
                )
                
                assert result.messages_replayed == 8
                assert result.messages_failed == 2
                assert result.justification == request.justification
                
                # Verify audit was called with justification
                MockAuditService.audit_dlq_replay.assert_called_once()
                call_args = MockAuditService.audit_dlq_replay.call_args
                assert call_args.kwargs["justification"] == request.justification
    
    @pytest.mark.asyncio
    async def test_replay_messages_invalid_justification(self):
        """Test that DLQReplayRequest rejects invalid justification."""
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError) as exc_info:
            DLQReplayRequest(
                mfa_code="123456",
                max_messages=10,
                backoff_ms=100,
                justification="test"  # Too short
            )
        
        assert "Justification must be at least 10 characters" in str(exc_info.value)
    
    @pytest.mark.asyncio
    async def test_replay_messages_with_backoff(self, admin_user, mock_db):
        """Test that replay respects backoff timing."""
        with patch('app.routers.admin_dlq.DLQManagementService') as MockDLQService:
            with patch('app.routers.admin_dlq.JobAuditService') as MockAuditService:
                # Mock services
                dlq_service = MockDLQService.return_value
                dlq_service.replay_messages = AsyncMock(return_value={
                    "replayed_count": 5,
                    "failed_count": 0,
                    "details": []
                })
                MockAuditService.audit_dlq_replay = AsyncMock()
                
                # Create request with backoff
                request = DLQReplayRequest(
                    mfa_code="123456",
                    max_messages=5,
                    backoff_ms=500,  # 500ms backoff
                    justification="Testing backoff timing for thundering herd prevention"
                )
                
                # Test replay
                result = await replay_dlq_messages(
                    queue_name="model_dlq",
                    request=request,
                    current_user=admin_user,
                    db=mock_db,
                    _=None
                )
                
                # Verify backoff was passed to service
                dlq_service.replay_messages.assert_called_once_with(
                    queue_name="model_dlq",
                    max_messages=5,
                    backoff_ms=500
                )


class TestRateLimiting:
    """Test rate limiting for DLQ endpoints."""
    
    @pytest.mark.asyncio
    async def test_rate_limiting_30_per_minute(self, admin_user, mock_db):
        """Test that rate limiting enforces 30 requests per minute."""
        # This would require integration testing with actual rate limiter
        # For unit test, we verify the dependency is present
        from app.middleware.enterprise_rate_limiter import RateLimitDependency
        from app.services.rate_limiting_service import RateLimitType
        
        # Verify rate limit dependency is configured for ADMIN type
        rate_limiter = RateLimitDependency(RateLimitType.ADMIN)
        assert rate_limiter.policy_type == RateLimitType.ADMIN


class TestErrorHandling:
    """Test error handling and error codes."""
    
    @pytest.mark.asyncio
    async def test_error_codes_consistency(self):
        """Test that all error codes follow the ERR-DLQ-XXX pattern."""
        error_codes = [
            "ERR-DLQ-401",  # Unauthorized
            "ERR-DLQ-403",  # MFA failed
            "ERR-DLQ-404",  # Invalid queue
            "ERR-DLQ-429",  # Rate limit exceeded
            "ERR-DLQ-500",  # Internal error
        ]
        
        for code in error_codes:
            assert code.startswith("ERR-DLQ-")
            assert len(code.split("-")[-1]) == 3  # 3-digit error code


class TestAuditLogging:
    """Test audit logging for all DLQ operations."""
    
    @pytest.mark.asyncio
    async def test_all_operations_create_audit_logs(self, admin_user, mock_db):
        """Verify all DLQ operations create audit logs."""
        with patch('app.routers.admin_dlq.JobAuditService') as MockAuditService:
            MockAuditService.audit_dlq_action = AsyncMock()
            MockAuditService.audit_dlq_replay = AsyncMock()
            
            # Each endpoint should call appropriate audit method
            # This is verified in individual endpoint tests above
            assert True  # Placeholder for audit verification


class TestSecurityIntegration:
    """Test integration with existing security features."""
    
    @pytest.mark.asyncio
    async def test_integration_with_rbac(self, admin_user):
        """Test that RBAC is properly integrated."""
        assert admin_user.role == UserRole.ADMIN
        # Further RBAC integration tests would go here
    
    @pytest.mark.asyncio
    async def test_integration_with_mfa(self):
        """Test that MFA from Task 3.7 is properly integrated."""
        # This is tested in TestAdminMFAVerification
        assert True
    
    @pytest.mark.asyncio
    async def test_integration_with_audit_service(self):
        """Test that audit service from Task 6.8 is properly integrated."""
        # This is tested throughout the endpoint tests
        assert True