"""
Test suite for Task 6.4: POST /jobs with transactional idempotency and enqueue.
Ultra-enterprise quality tests for job creation API.
"""

import asyncio
import json
import time
from datetime import datetime
from typing import Dict, Any, Optional
from unittest.mock import Mock, patch, MagicMock
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models import Job, User
from app.models.enums import JobStatus, JobType
from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.rate_limiter import RateLimiter


# Test fixtures
@pytest.fixture
def test_client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def test_user():
    """Create a test user."""
    return User(
        id=1,
        email="test@example.com",
        name="Test User",
        is_active=True,
    )


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=Session)
    return session


@pytest.fixture
def job_create_payload() -> Dict[str, Any]:
    """Valid job creation payload."""
    return {
        "type": "model",
        "params": {
            "model_type": "parametric",
            "dimensions": {"x": 100, "y": 50, "z": 25},
            "material": "aluminum",
        },
        "idempotency_key": f"test-{uuid4()}",
        "priority": 10,
    }


class TestJobCreation:
    """Test suite for job creation endpoint."""
    
    def test_create_job_success(
        self,
        test_client: TestClient,
        job_create_payload: Dict[str, Any],
        test_user: User,
        mock_db_session: Session,
    ):
        """Test successful job creation."""
        
        # Mock dependencies
        with patch("app.routers.jobs.get_db", return_value=mock_db_session):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                with patch("app.routers.jobs.publish_job_task") as mock_publish:
                    # Configure mock
                    mock_db_session.query.return_value.filter.return_value.first.return_value = None
                    mock_db_session.flush.return_value = None
                    mock_db_session.commit.return_value = None
                    
                    mock_publish.return_value = MagicMock(
                        job_id=str(uuid4()),
                        status="queued",
                        queue="model",
                        routing_key="jobs.model",
                    )
                    
                    # Make request
                    response = test_client.post(
                        "/api/v1/jobs",
                        json=job_create_payload,
                    )
                    
                    # Assertions
                    assert response.status_code == status.HTTP_201_CREATED
                    data = response.json()
                    
                    assert data["type"] == "model"
                    # GEMINI MEDIUM FIX: Job status should be "queued" after publishing to queue
                    assert data["status"] == "queued"
                    assert data["idempotency_key"] == job_create_payload["idempotency_key"]
                    assert data["queue"] == "model"
                    assert data["is_duplicate"] is False
                    assert "Location" in response.headers
    
    def test_idempotent_request_returns_existing(
        self,
        test_client: TestClient,
        job_create_payload: Dict[str, Any],
        test_user: User,
        mock_db_session: Session,
    ):
        """Test idempotent request returns existing job with 200."""
        
        # Create existing job
        existing_job = Job(
            id=123,
            type=JobType.MODEL,
            status=JobStatus.RUNNING,
            idempotency_key=job_create_payload["idempotency_key"],
            params=job_create_payload["params"],
            user_id=test_user.id,
            created_at=datetime.utcnow(),
            task_id=str(uuid4()),
            attempts=1,
            cancel_requested=False,
        )
        
        with patch("app.routers.jobs.get_db", return_value=mock_db_session):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                # Configure mock to return existing job
                mock_db_session.query.return_value.filter.return_value.first.return_value = existing_job
                
                # Make request
                response = test_client.post(
                    "/api/v1/jobs",
                    json=job_create_payload,
                )
                
                # Assertions
                assert response.status_code == status.HTTP_200_OK
                data = response.json()
                
                assert data["id"] == 123
                assert data["is_duplicate"] is True
                assert data["message"] == "Job already exists (idempotent request)"
    
    def test_invalid_job_type_returns_422(
        self,
        test_client: TestClient,
        test_user: User,
    ):
        """Test invalid job type returns 422."""
        
        invalid_payload = {
            "type": "invalid_type",
            "params": {"test": "data"},
            "idempotency_key": f"test-{uuid4()}",
        }
        
        with patch("app.routers.jobs.get_current_user", return_value=test_user):
            response = test_client.post(
                "/api/v1/jobs",
                json=invalid_payload,
            )
            
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
            data = response.json()
            assert "error" in data
            assert data["error"] == "ERR-JOB-400"
    
    def test_invalid_params_returns_422(
        self,
        test_client: TestClient,
        test_user: User,
    ):
        """Test invalid params returns 422."""
        
        invalid_payload = {
            "type": "model",
            "params": "not_a_dict",  # Invalid - should be dict
            "idempotency_key": f"test-{uuid4()}",
        }
        
        with patch("app.routers.jobs.get_current_user", return_value=test_user):
            response = test_client.post(
                "/api/v1/jobs",
                json=invalid_payload,
            )
            
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_rate_limit_per_user(
        self,
        test_client: TestClient,
        job_create_payload: Dict[str, Any],
        test_user: User,
    ):
        """Test per-user rate limiting returns 429."""
        
        with patch("app.routers.jobs.get_current_user", return_value=test_user):
            with patch("app.routers.jobs.per_user_rate_limiter.check_rate_limit", return_value=False):
                with patch("app.routers.jobs.per_user_rate_limiter.get_remaining", return_value=(0, 30)):
                    
                    response = test_client.post(
                        "/api/v1/jobs",
                        json=job_create_payload,
                    )
                    
                    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
                    data = response.json()
                    assert data["error"] == "ERR-JOB-RATE-LIMIT"
                    assert data["remaining"] == 0
                    assert data["limit"] == 60
    
    def test_global_rate_limit(
        self,
        test_client: TestClient,
        job_create_payload: Dict[str, Any],
        test_user: User,
    ):
        """Test global rate limiting returns 429."""
        
        with patch("app.routers.jobs.get_current_user", return_value=test_user):
            with patch("app.routers.jobs.per_user_rate_limiter.check_rate_limit", return_value=True):
                with patch("app.routers.jobs.global_rate_limiter.check_rate_limit", return_value=False):
                    with patch("app.routers.jobs.global_rate_limiter.get_remaining", return_value=(0, 45)):
                        
                        response = test_client.post(
                            "/api/v1/jobs",
                            json=job_create_payload,
                        )
                        
                        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
                        data = response.json()
                        assert data["error"] == "ERR-JOB-RATE-LIMIT"
                        assert data["limit"] == 500
    
    def test_database_conflict_returns_409(
        self,
        test_client: TestClient,
        job_create_payload: Dict[str, Any],
        test_user: User,
        mock_db_session: Session,
    ):
        """Test database conflict returns 409."""
        
        from sqlalchemy.exc import IntegrityError
        
        with patch("app.routers.jobs.get_db", return_value=mock_db_session):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                # Configure mock to raise IntegrityError
                mock_db_session.query.return_value.filter.return_value.first.return_value = None
                mock_db_session.flush.side_effect = IntegrityError(
                    "duplicate key",
                    "params",
                    "orig"
                )
                
                response = test_client.post(
                    "/api/v1/jobs",
                    json=job_create_payload,
                )
                
                assert response.status_code == status.HTTP_409_CONFLICT
                data = response.json()
                assert data["error"] == "ERR-JOB-409"
                assert data["retryable"] is True
    
    def test_concurrent_requests_same_idempotency_key(
        self,
        test_client: TestClient,
        job_create_payload: Dict[str, Any],
        test_user: User,
    ):
        """Test concurrent requests with same idempotency_key yield single job."""
        
        # This test simulates race condition handling
        from sqlalchemy.exc import IntegrityError
        
        existing_job = Job(
            id=456,
            type=JobType.MODEL,
            status=JobStatus.PENDING,
            idempotency_key=job_create_payload["idempotency_key"],
            params=job_create_payload["params"],
            user_id=test_user.id,
            created_at=datetime.utcnow(),
            attempts=0,
            cancel_requested=False,
        )
        
        with patch("app.routers.jobs.get_db") as mock_get_db:
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                mock_session = MagicMock(spec=Session)
                mock_get_db.return_value = mock_session
                
                # First call returns None (no existing job)
                # Flush raises IntegrityError (race condition)
                # Second call returns the job created by concurrent request
                mock_session.query.return_value.filter.return_value.first.side_effect = [
                    None,  # First check
                    existing_job,  # After IntegrityError
                ]
                
                mock_session.flush.side_effect = IntegrityError(
                    "duplicate key value violates unique constraint",
                    "idempotency_key",
                    "orig"
                )
                
                response = test_client.post(
                    "/api/v1/jobs",
                    json=job_create_payload,
                )
                
                # Should handle race condition gracefully
                assert response.status_code == status.HTTP_200_OK
                data = response.json()
                assert data["id"] == 456
                assert data["is_duplicate"] is True
                assert "race condition resolved" in data["message"]
    
    def test_job_types_routing(
        self,
        test_client: TestClient,
        test_user: User,
        mock_db_session: Session,
    ):
        """Test different job types route to correct queues."""
        
        job_type_queue_map = [
            ("ai", "default"),
            ("model", "model"),
            ("cam", "cam"),
            ("sim", "sim"),
            ("report", "report"),
            ("erp", "erp"),
        ]
        
        for job_type, expected_queue in job_type_queue_map:
            payload = {
                "type": job_type,
                "params": {"test": f"{job_type}_params"},
                "idempotency_key": f"test-{job_type}-{uuid4()}",
            }
            
            with patch("app.routers.jobs.get_db", return_value=mock_db_session):
                with patch("app.routers.jobs.get_current_user", return_value=test_user):
                    with patch("app.routers.jobs.publish_job_task") as mock_publish:
                        # Configure mock
                        mock_db_session.query.return_value.filter.return_value.first.return_value = None
                        mock_publish.return_value = MagicMock(
                            job_id=str(uuid4()),
                            queue=expected_queue,
                        )
                        
                        response = test_client.post(
                            "/api/v1/jobs",
                            json=payload,
                        )
                        
                        assert response.status_code == status.HTTP_201_CREATED
                        data = response.json()
                        assert data["queue"] == expected_queue
    
    def test_payload_size_limit(
        self,
        test_client: TestClient,
        test_user: User,
    ):
        """Test payload size limit enforcement (256KB)."""
        
        # Create oversized payload (> 256KB)
        large_data = "x" * (256 * 1024 + 1)
        oversized_payload = {
            "type": "model",
            "params": {"data": large_data},
            "idempotency_key": f"test-{uuid4()}",
        }
        
        with patch("app.routers.jobs.get_current_user", return_value=test_user):
            response = test_client.post(
                "/api/v1/jobs",
                json=oversized_payload,
            )
            
            # Should reject oversized payload
            assert response.status_code in [
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            ]
    
    def test_location_header_set_on_creation(
        self,
        test_client: TestClient,
        job_create_payload: Dict[str, Any],
        test_user: User,
        mock_db_session: Session,
    ):
        """Test Location header is set on successful creation."""
        
        with patch("app.routers.jobs.get_db", return_value=mock_db_session):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                with patch("app.routers.jobs.publish_job_task") as mock_publish:
                    # GEMINI MEDIUM FIX: Fix mock strategy for proper job ID assignment
                    # Configure mock to return None for idempotency check
                    mock_db_session.query.return_value.filter.return_value.first.return_value = None
                    
                    # Create a mock job instance that will be added to the session
                    mock_job = MagicMock(spec=Job)
                    mock_job.id = 789  # This ID should appear in Location header
                    mock_job.type = JobType.MODEL
                    mock_job.status = JobStatus.QUEUED
                    mock_job.idempotency_key = job_create_payload["idempotency_key"]
                    mock_job.created_at = datetime.utcnow()
                    mock_job.task_id = str(uuid4())
                    
                    # Mock the Job constructor to return our mock job
                    with patch("app.routers.jobs.Job", return_value=mock_job):
                        # Configure session mocks
                        mock_db_session.add.return_value = None
                        mock_db_session.flush.return_value = None
                        mock_db_session.commit.return_value = None
                        
                        mock_publish.return_value = MagicMock(
                            job_id=str(uuid4()),
                            status="queued",
                            queue="model",
                        )
                        
                        response = test_client.post(
                            "/api/v1/jobs",
                            json=job_create_payload,
                        )
                        
                        assert response.status_code == status.HTTP_201_CREATED
                        assert "Location" in response.headers
                        # Location header should contain the specific job ID
                        assert response.headers["Location"] == "/api/v1/jobs/789"


class TestIdempotencyEdgeCases:
    """Test edge cases for idempotency handling."""
    
    def test_empty_idempotency_key_rejected(
        self,
        test_client: TestClient,
        test_user: User,
    ):
        """Test empty idempotency key is rejected."""
        
        payload = {
            "type": "model",
            "params": {"test": "data"},
            "idempotency_key": "",  # Empty
        }
        
        with patch("app.routers.jobs.get_current_user", return_value=test_user):
            response = test_client.post(
                "/api/v1/jobs",
                json=payload,
            )
            
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_whitespace_idempotency_key_rejected(
        self,
        test_client: TestClient,
        test_user: User,
    ):
        """Test whitespace-only idempotency key is rejected."""
        
        payload = {
            "type": "model",
            "params": {"test": "data"},
            "idempotency_key": "   ",  # Whitespace only
        }
        
        with patch("app.routers.jobs.get_current_user", return_value=test_user):
            response = test_client.post(
                "/api/v1/jobs",
                json=payload,
            )
            
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    def test_long_idempotency_key_rejected(
        self,
        test_client: TestClient,
        test_user: User,
    ):
        """Test overly long idempotency key is rejected."""
        
        payload = {
            "type": "model",
            "params": {"test": "data"},
            "idempotency_key": "x" * 256,  # Too long (max 255)
        }
        
        with patch("app.routers.jobs.get_current_user", return_value=test_user):
            response = test_client.post(
                "/api/v1/jobs",
                json=payload,
            )
            
            assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestMetricsAndMonitoring:
    """Test metrics and monitoring aspects."""
    
    def test_job_creation_logged(
        self,
        test_client: TestClient,
        job_create_payload: Dict[str, Any],
        test_user: User,
        mock_db_session: Session,
    ):
        """Test job creation is properly logged."""
        
        with patch("app.routers.jobs.get_db", return_value=mock_db_session):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                with patch("app.routers.jobs.logger") as mock_logger:
                    with patch("app.routers.jobs.publish_job_task"):
                        mock_db_session.query.return_value.filter.return_value.first.return_value = None
                        
                        response = test_client.post(
                            "/api/v1/jobs",
                            json=job_create_payload,
                        )
                        
                        assert response.status_code == status.HTTP_201_CREATED
                        
                        # Check that appropriate logs were created
                        assert mock_logger.info.called
                        log_calls = mock_logger.info.call_args_list
                        
                        # Should log job creation
                        assert any(
                            "Job created successfully" in str(call)
                            for call in log_calls
                        )
    
    def test_rate_limit_logged(
        self,
        test_client: TestClient,
        job_create_payload: Dict[str, Any],
        test_user: User,
    ):
        """Test rate limiting is logged."""
        
        with patch("app.routers.jobs.get_current_user", return_value=test_user):
            with patch("app.routers.jobs.per_user_rate_limiter.check_rate_limit", return_value=False):
                with patch("app.routers.jobs.per_user_rate_limiter.get_remaining", return_value=(0, 30)):
                    with patch("app.routers.jobs.logger") as mock_logger:
                        
                        response = test_client.post(
                            "/api/v1/jobs",
                            json=job_create_payload,
                        )
                        
                        assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
                        
                        # Check that rate limit was logged
                        assert mock_logger.warning.called
                        log_calls = mock_logger.warning.call_args_list
                        assert any(
                            "rate limit exceeded" in str(call).lower()
                            for call in log_calls
                        )


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])