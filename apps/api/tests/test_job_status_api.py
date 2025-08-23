"""
Tests for Task 6.5 - GET /jobs/:id endpoint with queue position tracking.

Ultra enterprise-grade tests for job status API.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, Mock
import hashlib
import json
from uuid import uuid4

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import Job, User, Artefact, Role
from app.models.enums import JobStatus, JobType
from app.services.job_queue_service import JobQueueService
from app.core.database import get_db
from app.core.auth import get_current_user


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
        full_name="Test User",
        is_active=True,
    )


@pytest.fixture
def mock_db_session():
    """Create a mock database session."""
    session = MagicMock(spec=Session)
    
    # Setup basic query mock
    session.query = MagicMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    session.flush = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.scalar = MagicMock()
    
    return session


@pytest.fixture
def auth_headers():
    """Create authorization headers."""
    return {"Authorization": "Bearer test-token"}


class TestJobStatusEndpoint:
    """Test suite for GET /jobs/{job_id} endpoint."""
    
    def test_get_job_success_with_all_fields(
        self,
        client,
        db_session: Session,
        test_user: User,
        auth_headers,
    ):
        """Test successful job retrieval with all fields populated."""
        
        # Create a job with all fields
        job = Job(
            idempotency_key="test-job-complete",
            type=JobType.MODEL,
            status=JobStatus.COMPLETED,
            params={"design": "test"},
            user_id=test_user.id,
            priority=5,
            progress=100,
            attempts=2,
            cancel_requested=False,
            retry_count=0,
            max_retries=3,
            timeout_seconds=3600,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=10),
            finished_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            error_code=None,
            error_message=None,
            metrics={
                "current_step": "finalization",
                "last_progress_message": "Model generation completed",
                "last_progress_update": datetime.now(timezone.utc).isoformat(),
            },
        )
        db_session.add(job)
        db_session.flush()
        
        # Add artefacts
        artefact1 = Artefact(
            job_id=job.id,
            s3_bucket="artefacts",
            s3_key=f"models/{job.id}/model.fcstd",
            size_bytes=1024000,
            sha256="a" * 64,
            mime_type="application/octet-stream",
            type="model",
            created_by=test_user.id,
        )
        artefact2 = Artefact(
            job_id=job.id,
            s3_bucket="artefacts",
            s3_key=f"models/{job.id}/preview.png",
            size_bytes=204800,
            sha256="b" * 64,
            mime_type="image/png",
            type="preview",
            created_by=test_user.id,
        )
        db_session.add_all([artefact1, artefact2])
        db_session.commit()
        
        # Make request
        response = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)
        
        # Verify response
        assert response.status_code == status.HTTP_200_OK
        
        data = response.json()
        assert data["id"] == job.id
        assert data["type"] == "freecad_model"
        assert data["status"] == "completed"
        
        # Check progress
        assert data["progress"]["percent"] == 100
        assert data["progress"]["step"] == "finalization"
        assert data["progress"]["message"] == "Model generation completed"
        assert data["progress"]["updated_at"] is not None
        
        # Check metadata
        assert data["attempts"] == 2
        assert data["cancel_requested"] is False
        assert data["created_at"] is not None
        assert data["updated_at"] is not None
        assert data["started_at"] is not None
        assert data["finished_at"] is not None
        
        # Check artefacts
        assert len(data["artefacts"]) == 2
        artefact = data["artefacts"][0]
        assert artefact["id"] == artefact1.id
        assert artefact["type"] == "model"
        assert artefact["s3_key"] == f"models/{job.id}/model.fcstd"
        assert artefact["sha256"] == "a" * 64
        assert artefact["size"] == 1024000
        
        # No error for successful job
        assert data["last_error"] is None
        
        # No queue position for completed job
        assert data["queue_position"] is None
        
        # Check ETag header
        assert "ETag" in response.headers
        assert response.headers["ETag"].startswith('W/"')
    
    def test_get_job_with_queue_position(
        self,
        client,
        db_session: Session,
        test_user: User,
        auth_headers,
    ):
        """Test job retrieval with queue position calculation."""
        
        # Create multiple jobs in queue
        # Higher priority job (should be processed first)
        job1 = Job(
            idempotency_key="high-priority-job",
            type=JobType.MODEL,
            status=JobStatus.QUEUED,
            params={"design": "priority"},
            user_id=test_user.id,
            priority=10,  # Higher priority
            progress=0,
        )
        
        # Earlier job with same priority
        job2 = Job(
            idempotency_key="earlier-job",
            type=JobType.MODEL,
            status=JobStatus.QUEUED,
            params={"design": "earlier"},
            user_id=test_user.id,
            priority=5,  # Same priority as our test job
            progress=0,
        )
        
        # Currently running job
        job3 = Job(
            idempotency_key="running-job",
            type=JobType.MODEL,
            status=JobStatus.RUNNING,
            params={"design": "running"},
            user_id=test_user.id,
            priority=0,
            progress=50,
        )
        
        db_session.add_all([job1, job2, job3])
        db_session.flush()
        
        # Our test job (created after job2)
        test_job = Job(
            idempotency_key="test-job-queue",
            type=JobType.MODEL,
            status=JobStatus.QUEUED,
            params={"design": "test"},
            user_id=test_user.id,
            priority=5,  # Same priority as job2
            progress=0,
        )
        db_session.add(test_job)
        db_session.commit()
        
        # Make request
        response = client.get(f"/api/v1/jobs/{test_job.id}", headers=auth_headers)
        
        # Verify response
        assert response.status_code == status.HTTP_200_OK
        
        data = response.json()
        assert data["id"] == test_job.id
        assert data["status"] == "queued"
        
        # Queue position should be 4:
        # 1 running job + 1 higher priority job + 1 earlier same-priority job + 1 (this job) = position 4
        assert data["queue_position"] == 4
    
    def test_get_job_with_error_information(
        self,
        client,
        db_session: Session,
        test_user: User,
        auth_headers,
    ):
        """Test job retrieval with error information."""
        
        # Create a failed job
        job = Job(
            idempotency_key="failed-job",
            type=JobType.CAM,
            status=JobStatus.FAILED,
            params={"toolpath": "complex"},
            user_id=test_user.id,
            progress=75,
            attempts=3,
            error_code="ERR-CAM-001",
            error_message="Tool collision detected at path segment 42",
        )
        db_session.add(job)
        db_session.commit()
        
        # Make request
        response = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)
        
        # Verify response
        assert response.status_code == status.HTTP_200_OK
        
        data = response.json()
        assert data["id"] == job.id
        assert data["status"] == "failed"
        assert data["progress"]["percent"] == 75
        
        # Check error information
        assert data["last_error"] is not None
        assert data["last_error"]["code"] == "ERR-CAM-001"
        assert data["last_error"]["message"] == "Tool collision detected at path segment 42"
        
        # No queue position for failed job
        assert data["queue_position"] is None
    
    def test_get_job_not_found(
        self,
        client,
        auth_headers,
    ):
        """Test 404 response for non-existent job."""
        
        response = client.get("/api/v1/jobs/999999", headers=auth_headers)
        
        assert response.status_code == status.HTTP_404_NOT_FOUND
        data = response.json()
        assert "İş bulunamadı" in data["detail"] or "Job not found" in data["detail"]
    
    def test_get_job_unauthorized_user(
        self,
        client,
        db_session: Session,
        test_user: User,
    ):
        """Test 404 response when user is not the owner and not admin."""
        
        # Create job owned by test_user
        job = Job(
            idempotency_key="other-user-job",
            type=JobType.MODEL,
            status=JobStatus.RUNNING,
            params={"design": "private"},
            user_id=test_user.id,
        )
        db_session.add(job)
        db_session.commit()
        
        # Create another user and get their auth headers
        other_user = User(
            email="other@example.com",
            full_name="Other User",
        )
        db_session.add(other_user)
        db_session.commit()
        
        # Mock auth for other user
        with patch("app.routers.jobs.get_current_user") as mock_auth:
            mock_auth.return_value = other_user
            
            # Manually create headers for other user
            other_headers = {"Authorization": "Bearer fake-token"}
            
            response = client.get(f"/api/v1/jobs/{job.id}", headers=other_headers)
            
            # Should return 404 for security (don't reveal job exists)
            assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_etag_not_modified(
        self,
        client,
        db_session: Session,
        test_user: User,
        auth_headers,
    ):
        """Test ETag/If-None-Match for efficient polling."""
        
        # Create a job
        job = Job(
            idempotency_key="etag-test-job",
            type=JobType.MODEL,
            status=JobStatus.RUNNING,
            params={"design": "test"},
            user_id=test_user.id,
            progress=50,
        )
        db_session.add(job)
        db_session.commit()
        
        # First request to get ETag
        response1 = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)
        assert response1.status_code == status.HTTP_200_OK
        
        etag = response1.headers.get("ETag")
        assert etag is not None
        assert etag.startswith('W/"')
        
        # Second request with If-None-Match
        headers_with_etag = {**auth_headers, "If-None-Match": etag}
        response2 = client.get(f"/api/v1/jobs/{job.id}", headers=headers_with_etag)
        
        # Should return 304 Not Modified
        assert response2.status_code == status.HTTP_304_NOT_MODIFIED
        assert response2.headers.get("ETag") == etag
    
    def test_etag_changes_on_progress_update(
        self,
        client,
        db_session: Session,
        test_user: User,
        auth_headers,
    ):
        """Test that ETag changes when job progress updates."""
        
        # Create a job
        job = Job(
            idempotency_key="etag-change-job",
            type=JobType.MODEL,
            status=JobStatus.RUNNING,
            params={"design": "test"},
            user_id=test_user.id,
            progress=30,
        )
        db_session.add(job)
        db_session.commit()
        
        # First request to get initial ETag
        response1 = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)
        assert response1.status_code == status.HTTP_200_OK
        etag1 = response1.headers.get("ETag")
        
        # Update job progress
        job.progress = 60
        job.metrics = {
            "current_step": "processing",
            "last_progress_message": "Processing geometry",
            "last_progress_update": datetime.now(timezone.utc).isoformat(),
        }
        db_session.commit()
        
        # Second request should have different ETag
        response2 = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)
        assert response2.status_code == status.HTTP_200_OK
        etag2 = response2.headers.get("ETag")
        
        # ETags should be different
        assert etag1 != etag2
        
        # Using old ETag should still return 304 if we send it
        headers_with_old_etag = {**auth_headers, "If-None-Match": etag1}
        response3 = client.get(f"/api/v1/jobs/{job.id}", headers=headers_with_old_etag)
        assert response3.status_code == status.HTTP_200_OK  # Old ETag, so return full response
    
    def test_running_job_has_zero_queue_position(
        self,
        client,
        db_session: Session,
        test_user: User,
        auth_headers,
    ):
        """Test that running jobs have queue position 0."""
        
        # Create a running job
        job = Job(
            idempotency_key="running-position-job",
            type=JobType.MODEL,
            status=JobStatus.RUNNING,
            params={"design": "active"},
            user_id=test_user.id,
            progress=45,
        )
        db_session.add(job)
        db_session.commit()
        
        # Make request
        response = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)
        
        # Verify response
        assert response.status_code == status.HTTP_200_OK
        
        data = response.json()
        assert data["status"] == "running"
        assert data["queue_position"] == 0  # Currently processing
    
    def test_cache_control_header(
        self,
        client,
        db_session: Session,
        test_user: User,
        auth_headers,
    ):
        """Test Cache-Control header for polling efficiency."""
        
        # Create a job
        job = Job(
            idempotency_key="cache-test-job",
            type=JobType.MODEL,
            status=JobStatus.QUEUED,
            params={"design": "test"},
            user_id=test_user.id,
        )
        db_session.add(job)
        db_session.commit()
        
        # Make request
        response = client.get(f"/api/v1/jobs/{job.id}", headers=auth_headers)
        
        # Verify Cache-Control header
        assert response.status_code == status.HTTP_200_OK
        assert response.headers.get("Cache-Control") == "private, max-age=1"
    
    def test_admin_can_access_any_job(
        self,
        client,
        db_session: Session,
        test_user: User,
    ):
        """Test that admin users can access any job."""
        
        # Create job owned by test_user
        job = Job(
            idempotency_key="admin-access-job",
            type=JobType.MODEL,
            status=JobStatus.COMPLETED,
            params={"design": "admin-test"},
            user_id=test_user.id,
            progress=100,
        )
        db_session.add(job)
        
        # Create admin user with admin role
        admin_user = User(
            email="admin@example.com",
            full_name="Admin User",
        )
        db_session.add(admin_user)
        db_session.commit()
        
        # Add admin role (simplified for test - adjust based on your RBAC implementation)
        admin_role = db_session.query(Role).filter_by(name="admin").first()
        if not admin_role:
            admin_role = Role(name="admin", description="Administrator")
            db_session.add(admin_role)
        admin_user.roles.append(admin_role)
        db_session.commit()
        
        # Mock auth for admin user
        with patch("app.routers.jobs.get_current_user") as mock_auth:
            mock_auth.return_value = admin_user
            
            admin_headers = {"Authorization": "Bearer admin-token"}
            response = client.get(f"/api/v1/jobs/{job.id}", headers=admin_headers)
            
            # Admin should be able to access the job
            assert response.status_code == status.HTTP_200_OK
            data = response.json()
            assert data["id"] == job.id


class TestQueuePositionCalculation:
    """Test suite for queue position calculation logic."""
    
    def test_queue_position_with_different_job_types(
        self,
        db_session: Session,
    ):
        """Test queue position calculation across different job types in same queue."""
        
        user = User(email="test@example.com", full_name="Test User")
        db_session.add(user)
        db_session.flush()
        
        # Create jobs of different types that use the same queue
        # Assuming FREECAD_MODEL and FREECAD_CAM use 'model' and 'cam' queues respectively
        
        # Running job in model queue
        running_model = Job(
            idempotency_key="running-model",
            type=JobType.MODEL,
            status=JobStatus.RUNNING,
            params={},
            user_id=user.id,
        )
        
        # Queued jobs in model queue
        queued_model1 = Job(
            idempotency_key="queued-model-1",
            type=JobType.MODEL,
            status=JobStatus.QUEUED,
            params={},
            user_id=user.id,
            priority=5,
        )
        
        queued_model2 = Job(
            idempotency_key="queued-model-2",
            type=JobType.MODEL,
            status=JobStatus.QUEUED,
            params={},
            user_id=user.id,
            priority=3,
        )
        
        # Job in different queue (should not affect position)
        queued_cam = Job(
            idempotency_key="queued-cam",
            type=JobType.CAM,
            status=JobStatus.QUEUED,
            params={},
            user_id=user.id,
            priority=10,
        )
        
        db_session.add_all([running_model, queued_model1, queued_model2, queued_cam])
        db_session.commit()
        
        # Test position for lower priority model job
        position = JobQueueService.get_queue_position(db_session, queued_model2)
        # Should be: 1 running + 1 higher priority queued + 1 (self) = 3
        assert position == 3
        
        # Test position for CAM job (different queue)
        position_cam = JobQueueService.get_queue_position(db_session, queued_cam)
        # Should be 1 (first in its queue)
        assert position_cam == 1
    
    def test_queue_position_none_for_terminal_states(
        self,
        db_session: Session,
    ):
        """Test that terminal state jobs have no queue position."""
        
        user = User(email="test@example.com", full_name="Test User")
        db_session.add(user)
        db_session.flush()
        
        terminal_states = [
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
            JobStatus.TIMEOUT,
        ]
        
        for status in terminal_states:
            job = Job(
                idempotency_key=f"terminal-{status.value}",
                type=JobType.MODEL,
                status=status,
                params={},
                user_id=user.id,
            )
            db_session.add(job)
        
        db_session.commit()
        
        # All terminal state jobs should have None position
        for job in db_session.query(Job).filter(Job.status.in_(terminal_states)).all():
            position = JobQueueService.get_queue_position(db_session, job)
            assert position is None