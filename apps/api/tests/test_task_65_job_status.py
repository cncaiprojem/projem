"""
Test suite for Task 6.5: GET /jobs/{id} endpoint with queue position tracking.
Ultra-enterprise quality tests for job status API.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
from unittest.mock import Mock, patch, MagicMock
from uuid import uuid4

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import app
from app.models import Job, User, Artefact
from app.models.enums import JobStatus, JobType
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
    user = Mock(spec=User)
    user.id = 1
    user.email = "test@example.com"
    user.full_name = "Test User"
    user.is_active = True
    user.roles = []
    return user


@pytest.fixture
def admin_user():
    """Create an admin user."""
    user = Mock(spec=User)
    user.id = 2
    user.email = "admin@example.com"
    user.full_name = "Admin User"
    user.is_active = True
    
    # Add admin role
    admin_role = Mock()
    admin_role.name = "admin"
    user.roles = [admin_role]
    return user


@pytest.fixture
def mock_job_with_artefacts(test_user):
    """Create a mock job with artefacts."""
    job = Mock(spec=Job)
    job.id = 123
    job.idempotency_key = "test-job-123"
    job.type = JobType.MODEL
    job.status = JobStatus.COMPLETED
    job.params = {"design": "test", "material": "aluminum"}
    job.user_id = test_user.id
    job.priority = 5
    job.progress = 100
    job.attempts = 1
    job.cancel_requested = False
    job.retry_count = 0
    job.max_retries = 3
    job.timeout_seconds = 3600
    job.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    job.updated_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    job.started_at = datetime.now(timezone.utc) - timedelta(minutes=30)
    job.finished_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    job.error_code = None
    job.error_message = None
    job.metrics = {
        "current_step": "finalization",
        "last_progress_message": "Model generation completed",
        "last_progress_update": datetime.now(timezone.utc).isoformat(),
    }
    
    # Create mock artefacts
    artefact1 = Mock(spec=Artefact)
    artefact1.id = 1
    artefact1.job_id = job.id
    artefact1.type = "model"
    artefact1.s3_key = f"models/{job.id}/model.fcstd"
    artefact1.s3_bucket = "artefacts"
    artefact1.sha256 = "a" * 64
    artefact1.size_bytes = 1024000
    
    artefact2 = Mock(spec=Artefact)
    artefact2.id = 2
    artefact2.job_id = job.id
    artefact2.type = "preview"
    artefact2.s3_key = f"models/{job.id}/preview.png"
    artefact2.s3_bucket = "artefacts"
    artefact2.sha256 = "b" * 64
    artefact2.size_bytes = 204800
    
    job.artefacts = [artefact1, artefact2]
    
    return job


class TestJobStatusEndpoint:
    """Test suite for GET /jobs/{job_id} endpoint."""
    
    def test_get_job_success_with_all_fields(
        self,
        test_client: TestClient,
        test_user,
        mock_job_with_artefacts,
    ):
        """Test successful job retrieval with all fields populated."""
        
        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job_with_artefacts
        
        # Mock dependencies
        with patch("app.routers.jobs.get_db", return_value=mock_db):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                with patch("app.routers.jobs.JobQueueService.get_queue_position", return_value=None):
                    
                    # Make request
                    response = test_client.get(f"/api/v1/jobs/{mock_job_with_artefacts.id}")
                    
                    # Verify response
                    assert response.status_code == status.HTTP_200_OK
                    
                    data = response.json()
                    assert data["id"] == mock_job_with_artefacts.id
                    assert data["type"] == "freecad_model"
                    assert data["status"] == "completed"
                    
                    # Check progress
                    assert data["progress"]["percent"] == 100
                    assert data["progress"]["step"] == "finalization"
                    assert data["progress"]["message"] == "Model generation completed"
                    assert data["progress"]["updated_at"] is not None
                    
                    # Check metadata
                    assert data["attempts"] == 1
                    assert data["cancel_requested"] is False
                    assert data["created_at"] is not None
                    assert data["updated_at"] is not None
                    assert data["started_at"] is not None
                    assert data["finished_at"] is not None
                    
                    # Check artefacts
                    assert len(data["artefacts"]) == 2
                    artefact = data["artefacts"][0]
                    assert artefact["id"] == 1
                    assert artefact["type"] == "model"
                    assert artefact["s3_key"] == f"models/{mock_job_with_artefacts.id}/model.fcstd"
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
        test_client: TestClient,
        test_user,
    ):
        """Test job retrieval with queue position calculation."""
        
        # Create a queued job
        queued_job = Mock(spec=Job)
        queued_job.id = 456
        queued_job.type = JobType.MODEL
        queued_job.status = JobStatus.QUEUED
        queued_job.params = {"design": "queued"}
        queued_job.user_id = test_user.id
        queued_job.priority = 5
        queued_job.progress = 0
        queued_job.attempts = 0
        queued_job.cancel_requested = False
        queued_job.created_at = datetime.now(timezone.utc)
        queued_job.updated_at = datetime.now(timezone.utc)
        queued_job.started_at = None
        queued_job.finished_at = None
        queued_job.error_code = None
        queued_job.error_message = None
        queued_job.metrics = None
        queued_job.artefacts = []
        
        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = queued_job
        
        # Mock dependencies
        with patch("app.routers.jobs.get_db", return_value=mock_db):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                # Mock queue position calculation to return position 3
                with patch("app.routers.jobs.JobQueueService.get_queue_position", return_value=3):
                    
                    # Make request
                    response = test_client.get(f"/api/v1/jobs/{queued_job.id}")
                    
                    # Verify response
                    assert response.status_code == status.HTTP_200_OK
                    
                    data = response.json()
                    assert data["id"] == queued_job.id
                    assert data["status"] == "queued"
                    assert data["queue_position"] == 3
    
    def test_get_job_with_error_information(
        self,
        test_client: TestClient,
        test_user,
    ):
        """Test job retrieval with error information."""
        
        # Create a failed job
        failed_job = Mock(spec=Job)
        failed_job.id = 789
        failed_job.type = JobType.CAM
        failed_job.status = JobStatus.FAILED
        failed_job.params = {"toolpath": "complex"}
        failed_job.user_id = test_user.id
        failed_job.progress = 75
        failed_job.attempts = 3
        failed_job.cancel_requested = False
        failed_job.error_code = "ERR-CAM-001"
        failed_job.error_message = "Tool collision detected at path segment 42"
        failed_job.created_at = datetime.now(timezone.utc)
        failed_job.updated_at = datetime.now(timezone.utc)
        failed_job.started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        failed_job.finished_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        failed_job.metrics = None
        failed_job.artefacts = []
        
        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = failed_job
        
        # Mock dependencies
        with patch("app.routers.jobs.get_db", return_value=mock_db):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                with patch("app.routers.jobs.JobQueueService.get_queue_position", return_value=None):
                    
                    # Make request
                    response = test_client.get(f"/api/v1/jobs/{failed_job.id}")
                    
                    # Verify response
                    assert response.status_code == status.HTTP_200_OK
                    
                    data = response.json()
                    assert data["id"] == failed_job.id
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
        test_client: TestClient,
        test_user,
    ):
        """Test 404 response for non-existent job."""
        
        # Mock database session to return None
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None
        
        # Mock dependencies
        with patch("app.routers.jobs.get_db", return_value=mock_db):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                
                # Make request
                response = test_client.get("/api/v1/jobs/999999")
                
                # Verify 404 response
                assert response.status_code == status.HTTP_404_NOT_FOUND
                data = response.json()
                assert "İş bulunamadı" in data["detail"] or "Job not found" in data["detail"]
    
    def test_get_job_unauthorized_user(
        self,
        test_client: TestClient,
        test_user,
    ):
        """Test 404 response when user is not the owner and not admin."""
        
        # Create job owned by different user
        other_user_job = Mock(spec=Job)
        other_user_job.id = 321
        other_user_job.user_id = 999  # Different user ID
        other_user_job.type = JobType.MODEL
        other_user_job.status = JobStatus.RUNNING
        
        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = other_user_job
        
        # Mock dependencies
        with patch("app.routers.jobs.get_db", return_value=mock_db):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                
                # Make request
                response = test_client.get(f"/api/v1/jobs/{other_user_job.id}")
                
                # Should return 404 for security (don't reveal job exists)
                assert response.status_code == status.HTTP_404_NOT_FOUND
    
    def test_admin_can_access_any_job(
        self,
        test_client: TestClient,
        test_user,
        admin_user,
    ):
        """Test that admin users can access any job."""
        
        # Create job owned by test_user
        user_job = Mock(spec=Job)
        user_job.id = 654
        user_job.user_id = test_user.id  # Different from admin
        user_job.type = JobType.MODEL
        user_job.status = JobStatus.COMPLETED
        user_job.params = {}
        user_job.progress = 100
        user_job.attempts = 1
        user_job.cancel_requested = False
        user_job.error_code = None
        user_job.error_message = None
        user_job.metrics = None
        user_job.artefacts = []
        user_job.created_at = datetime.now(timezone.utc)
        user_job.updated_at = datetime.now(timezone.utc)
        user_job.started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        user_job.finished_at = datetime.now(timezone.utc)
        
        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = user_job
        
        # Mock dependencies with admin user
        with patch("app.routers.jobs.get_db", return_value=mock_db):
            with patch("app.routers.jobs.get_current_user", return_value=admin_user):
                with patch("app.routers.jobs.JobQueueService.get_queue_position", return_value=None):
                    
                    # Make request as admin
                    response = test_client.get(f"/api/v1/jobs/{user_job.id}")
                    
                    # Admin should be able to access the job
                    assert response.status_code == status.HTTP_200_OK
                    data = response.json()
                    assert data["id"] == user_job.id
    
    def test_etag_not_modified(
        self,
        test_client: TestClient,
        test_user,
    ):
        """Test ETag/If-None-Match for efficient polling."""
        
        # Create a job
        job = Mock(spec=Job)
        job.id = 888
        job.type = JobType.MODEL
        job.status = JobStatus.RUNNING
        job.params = {}
        job.user_id = test_user.id
        job.progress = 50
        job.attempts = 1
        job.cancel_requested = False
        job.error_code = None
        job.error_message = None
        job.metrics = None
        job.artefacts = []
        job.created_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        job.started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        job.finished_at = None
        
        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = job
        
        # Mock dependencies
        with patch("app.routers.jobs.get_db", return_value=mock_db):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                with patch("app.routers.jobs.JobQueueService.get_queue_position", return_value=0):
                    
                    # First request to get ETag
                    response1 = test_client.get(f"/api/v1/jobs/{job.id}")
                    assert response1.status_code == status.HTTP_200_OK
                    
                    etag = response1.headers.get("ETag")
                    assert etag is not None
                    assert etag.startswith('W/"')
                    
                    # Second request with If-None-Match
                    response2 = test_client.get(
                        f"/api/v1/jobs/{job.id}",
                        headers={"If-None-Match": etag}
                    )
                    
                    # Should return 304 Not Modified
                    assert response2.status_code == status.HTTP_304_NOT_MODIFIED
                    assert response2.headers.get("ETag") == etag
    
    def test_cache_control_header(
        self,
        test_client: TestClient,
        test_user,
    ):
        """Test Cache-Control header for polling efficiency."""
        
        # Create a job
        job = Mock(spec=Job)
        job.id = 777
        job.type = JobType.MODEL
        job.status = JobStatus.QUEUED
        job.params = {}
        job.user_id = test_user.id
        job.progress = 0
        job.attempts = 0
        job.cancel_requested = False
        job.error_code = None
        job.error_message = None
        job.metrics = None
        job.artefacts = []
        job.created_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)
        job.started_at = None
        job.finished_at = None
        
        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = job
        
        # Mock dependencies
        with patch("app.routers.jobs.get_db", return_value=mock_db):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                with patch("app.routers.jobs.JobQueueService.get_queue_position", return_value=2):
                    
                    # Make request
                    response = test_client.get(f"/api/v1/jobs/{job.id}")
                    
                    # Verify Cache-Control header
                    assert response.status_code == status.HTTP_200_OK
                    assert response.headers.get("Cache-Control") == "private, max-age=1"
    
    def test_running_job_has_zero_queue_position(
        self,
        test_client: TestClient,
        test_user,
    ):
        """Test that running jobs have queue position 0."""
        
        # Create a running job
        running_job = Mock(spec=Job)
        running_job.id = 555
        running_job.type = JobType.MODEL
        running_job.status = JobStatus.RUNNING
        running_job.params = {}
        running_job.user_id = test_user.id
        running_job.progress = 45
        running_job.attempts = 1
        running_job.cancel_requested = False
        running_job.error_code = None
        running_job.error_message = None
        running_job.metrics = {
            "current_step": "processing",
            "last_progress_message": "Processing geometry",
        }
        running_job.artefacts = []
        running_job.created_at = datetime.now(timezone.utc)
        running_job.updated_at = datetime.now(timezone.utc)
        running_job.started_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        running_job.finished_at = None
        
        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = running_job
        
        # Mock dependencies
        with patch("app.routers.jobs.get_db", return_value=mock_db):
            with patch("app.routers.jobs.get_current_user", return_value=test_user):
                # Queue position should be 0 for running jobs
                with patch("app.routers.jobs.JobQueueService.get_queue_position", return_value=0):
                    
                    # Make request
                    response = test_client.get(f"/api/v1/jobs/{running_job.id}")
                    
                    # Verify response
                    assert response.status_code == status.HTTP_200_OK
                    
                    data = response.json()
                    assert data["status"] == "running"
                    assert data["queue_position"] == 0  # Currently processing