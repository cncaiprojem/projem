"""
Comprehensive tests for job cancellation functionality (Task 6.6).

Tests:
- Cancellation API endpoint
- Idempotent cancellation
- Redis caching
- Worker cooperative cancellation
- Audit logging
- Authorization checks
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.core.redis_config import get_redis_client
from app.models.enums import JobStatus, JobType, UserRole
from app.models.job import Job
from app.models.user import User
from app.services.job_cancellation_service import (
    JobCancelledError,
    JobCancellationService,
    check_cancel,
    job_cancellation_service,
)
from app.tasks.cad import cad_build_task


class TestJobCancellationService:
    """Test the job cancellation service."""
    
    @pytest.fixture
    def cancellation_service(self):
        """Create a cancellation service instance."""
        return JobCancellationService()
    
    @pytest.fixture
    def mock_job(self, db: Session):
        """Create a test job."""
        job = Job(
            idempotency_key="test-cancel-key",
            type=JobType.CAD,
            status=JobStatus.IN_PROGRESS,
            params={"test": "params"},
            user_id=1,
            progress=25,
            cancel_requested=False,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    
    @pytest.mark.asyncio
    async def test_request_cancellation_success(
        self,
        cancellation_service: JobCancellationService,
        mock_job: Job,
        db: Session
    ):
        """Test successful cancellation request."""
        # Request cancellation
        result = await cancellation_service.request_cancellation(
            db=db,
            job_id=mock_job.id,
            user_id=1,
            reason="User requested",
            ip_address="127.0.0.1",
            user_agent="TestAgent/1.0"
        )
        
        # Check result
        assert result["success"] is True
        assert result["job_id"] == mock_job.id
        assert result["cancel_requested"] is True
        assert result["was_already_requested"] is False
        
        # Verify database update
        db.refresh(mock_job)
        assert mock_job.cancel_requested is True
        assert mock_job.metrics is not None
        assert "cancellation" in mock_job.metrics
        assert mock_job.metrics["cancellation"]["requested_by"] == 1
        assert mock_job.metrics["cancellation"]["reason"] == "User requested"
    
    @pytest.mark.asyncio
    async def test_request_cancellation_idempotent(
        self,
        cancellation_service: JobCancellationService,
        mock_job: Job,
        db: Session
    ):
        """Test that cancellation request is idempotent."""
        # First request
        result1 = await cancellation_service.request_cancellation(
            db=db,
            job_id=mock_job.id,
            user_id=1,
            reason="First request"
        )
        
        assert result1["success"] is True
        assert result1["was_already_requested"] is False
        
        # Second request (idempotent)
        result2 = await cancellation_service.request_cancellation(
            db=db,
            job_id=mock_job.id,
            user_id=2,
            reason="Second request"
        )
        
        assert result2["success"] is True
        assert result2["was_already_requested"] is True
        assert result2["message"] == "İptal zaten istenmişti"
    
    @pytest.mark.asyncio
    async def test_request_cancellation_terminal_state(
        self,
        cancellation_service: JobCancellationService,
        db: Session
    ):
        """Test cancellation request for job in terminal state."""
        # Create completed job
        job = Job(
            idempotency_key="test-completed",
            type=JobType.CAD,
            status=JobStatus.COMPLETED,
            params={"test": "params"},
            cancel_requested=False,
        )
        db.add(job)
        db.commit()
        
        # Request cancellation
        result = await cancellation_service.request_cancellation(
            db=db,
            job_id=job.id
        )
        
        # Should return success (idempotent)
        assert result["success"] is True
        assert result["status"] == "completed"
        assert result["already_cancelled"] is False
        assert "zaten completed durumunda" in result["message"]
    
    @pytest.mark.asyncio
    async def test_request_cancellation_job_not_found(
        self,
        cancellation_service: JobCancellationService,
        db: Session
    ):
        """Test cancellation request for non-existent job."""
        result = await cancellation_service.request_cancellation(
            db=db,
            job_id=99999
        )
        
        assert result["success"] is False
        assert result["error"] == "Job not found"
        assert result["job_id"] == 99999
    
    def test_check_cancellation_raises_error(
        self,
        cancellation_service: JobCancellationService,
        mock_job: Job,
        db: Session
    ):
        """Test that check_cancellation raises JobCancelledError when cancelled."""
        # Set job as cancelled
        mock_job.cancel_requested = True
        db.commit()
        
        # Check should raise error
        with pytest.raises(JobCancelledError) as exc_info:
            cancellation_service.check_cancellation(db, mock_job.id)
        
        assert exc_info.value.job_id == mock_job.id
        assert "cancellation has been requested" in str(exc_info.value)
    
    def test_check_cancellation_no_error_when_not_cancelled(
        self,
        cancellation_service: JobCancellationService,
        mock_job: Job,
        db: Session
    ):
        """Test that check_cancellation doesn't raise when not cancelled."""
        # Job is not cancelled
        result = cancellation_service.check_cancellation(db, mock_job.id)
        assert result is False
    
    def test_mark_job_cancelled(
        self,
        cancellation_service: JobCancellationService,
        mock_job: Job,
        db: Session
    ):
        """Test marking a job as cancelled."""
        # Mark as cancelled with progress
        result = cancellation_service.mark_job_cancelled(
            db=db,
            job_id=mock_job.id,
            final_progress={"percent": 50, "step": "processing"},
            cancellation_point="worker_check"
        )
        
        assert result is True
        
        # Check database update
        db.refresh(mock_job)
        assert mock_job.status == "cancelled"
        assert mock_job.finished_at is not None
        assert mock_job.metrics["cancellation_completed"]["cancellation_point"] == "worker_check"
        # CRITICAL FIX: job.progress is an integer, not a dict!
        assert mock_job.progress == 50  # Should be updated to 50 from final_progress["percent"]
        assert mock_job.metrics["percent"] == 50  # The dict data goes into metrics
        assert mock_job.metrics["step"] == "processing"


class TestJobCancellationAPI:
    """Test the cancellation API endpoint."""
    
    @pytest.fixture
    def auth_headers(self):
        """Mock authentication headers."""
        return {"Authorization": "Bearer test-token"}
    
    @pytest.fixture
    def mock_current_user(self):
        """Create a mock current user."""
        user = MagicMock(spec=User)
        user.id = 1
        user.role = UserRole.USER
        return user
    
    @pytest.fixture
    def mock_admin_user(self):
        """Create a mock admin user."""
        user = MagicMock(spec=User)
        user.id = 2
        user.role = UserRole.ADMIN
        return user
    
    def test_cancel_job_success(
        self,
        client,
        mock_job: Job,
        mock_current_user,
        auth_headers,
        db: Session
    ):
        """Test successful job cancellation via API."""
        # Mock authentication
        with patch("app.core.auth.get_current_user", return_value=mock_current_user):
            # Mock the async cancellation service
            with patch.object(
                job_cancellation_service,
                "request_cancellation",
                new_callable=AsyncMock
            ) as mock_cancel:
                mock_cancel.return_value = {
                    "success": True,
                    "status": "in_progress",
                    "cancel_requested": True,
                    "was_already_requested": False,
                    "message": "İptal isteği alındı / Cancellation requested"
                }
                
                # Make request
                response = client.post(
                    f"/api/v1/jobs/{mock_job.id}/cancel",
                    headers=auth_headers
                )
                
                assert response.status_code == status.HTTP_200_OK
                data = response.json()
                
                assert data["job_id"] == mock_job.id
                assert data["cancel_requested"] is True
                assert data["message"] == "İptal isteği alındı / Cancellation requested"
                assert data["already_cancelled"] is False
                
                # Verify service was called
                mock_cancel.assert_called_once()
    
    def test_cancel_job_not_found(
        self,
        client,
        mock_current_user,
        auth_headers,
        db: Session
    ):
        """Test cancellation for non-existent job."""
        with patch("app.core.auth.get_current_user", return_value=mock_current_user):
            response = client.post(
                "/api/v1/jobs/99999/cancel",
                headers=auth_headers
            )
            
            assert response.status_code == status.HTTP_404_NOT_FOUND
            data = response.json()
            assert "İş bulunamadı" in data["detail"]
    
    def test_cancel_job_unauthorized(
        self,
        client,
        mock_job: Job,
        db: Session
    ):
        """Test cancellation without authentication."""
        # Create job owned by another user
        mock_job.user_id = 999
        db.commit()
        
        # Mock user who is not owner
        non_owner = MagicMock(spec=User)
        non_owner.id = 1
        non_owner.role = UserRole.USER
        
        with patch("app.core.auth.get_current_user", return_value=non_owner):
            with patch("app.core.config.settings.DEV_AUTH_BYPASS", False):
                response = client.post(f"/api/v1/jobs/{mock_job.id}/cancel")
                
                assert response.status_code == status.HTTP_403_FORBIDDEN
                data = response.json()
                assert "yetkiniz yok" in data["detail"]
    
    def test_cancel_job_admin_can_cancel_any(
        self,
        client,
        mock_job: Job,
        mock_admin_user,
        auth_headers,
        db: Session
    ):
        """Test that admin can cancel any job."""
        # Job owned by different user
        mock_job.user_id = 999
        db.commit()
        
        with patch("app.core.auth.get_current_user", return_value=mock_admin_user):
            with patch.object(
                job_cancellation_service,
                "request_cancellation",
                new_callable=AsyncMock
            ) as mock_cancel:
                mock_cancel.return_value = {
                    "success": True,
                    "status": "in_progress",
                    "cancel_requested": True,
                    "was_already_requested": False
                }
                
                response = client.post(
                    f"/api/v1/jobs/{mock_job.id}/cancel",
                    headers=auth_headers
                )
                
                assert response.status_code == status.HTTP_200_OK
    
    def test_cancel_job_idempotent(
        self,
        client,
        mock_job: Job,
        mock_current_user,
        auth_headers,
        db: Session
    ):
        """Test that cancellation is idempotent."""
        with patch("app.core.auth.get_current_user", return_value=mock_current_user):
            with patch.object(
                job_cancellation_service,
                "request_cancellation",
                new_callable=AsyncMock
            ) as mock_cancel:
                # Second cancellation (already cancelled)
                mock_cancel.return_value = {
                    "success": True,
                    "status": "cancelled",
                    "already_cancelled": True,
                    "was_already_requested": True,
                    "message": "İptal zaten istenmişti"
                }
                
                response = client.post(
                    f"/api/v1/jobs/{mock_job.id}/cancel",
                    headers=auth_headers
                )
                
                assert response.status_code == status.HTTP_200_OK
                data = response.json()
                assert data["already_cancelled"] is True


class TestWorkerCancellation:
    """Test worker-side cancellation checks."""
    
    @pytest.fixture
    def mock_job_for_worker(self, db: Session):
        """Create a job for worker testing."""
        job = Job(
            idempotency_key="worker-test",
            type=JobType.CAD,
            status=JobStatus.IN_PROGRESS,
            params={"model": "test"},
            cancel_requested=False,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    
    def test_worker_check_cancel_stops_processing(
        self,
        mock_job_for_worker: Job,
        db: Session
    ):
        """Test that worker stops when cancellation is detected."""
        # Set job as cancelled
        mock_job_for_worker.cancel_requested = True
        db.commit()
        
        # Simulate worker checking
        with pytest.raises(JobCancelledError):
            check_cancel(db, mock_job_for_worker.id)
    
    @patch("app.tasks.cad.build_from_plan")
    @patch("app.tasks.cad.Project")
    def test_cad_task_handles_cancellation(
        self,
        mock_project_class,
        mock_build,
        mock_job_for_worker: Job,
        db: Session
    ):
        """Test that CAD task handles cancellation properly."""
        # Mock project
        mock_project = MagicMock()
        mock_project.id = mock_job_for_worker.id
        mock_project.summary_json = {"plan": {"test": "data"}}
        mock_project_class.query.return_value.get.return_value = mock_project
        
        # Mock build function
        mock_build.return_value = ({"model": "/tmp/test.fcstd"}, {"ok": True})
        
        # Request cancellation mid-task
        mock_job_for_worker.cancel_requested = True
        db.commit()
        
        # Run task - should detect cancellation
        with patch("app.tasks.cad.SessionLocal", return_value=db):
            with patch("app.tasks.cad.check_cancel") as mock_check:
                # Make check_cancel raise on second call
                mock_check.side_effect = [None, JobCancelledError(mock_job_for_worker.id)]
                
                result = cad_build_task(mock_job_for_worker.id)
                
                assert result["status"] == "cancelled"
                assert result["project_id"] == mock_job_for_worker.id
                
                # Task 6.6 fix from PR #231: Verify database state after cancellation
                db.refresh(mock_job_for_worker)
                assert mock_job_for_worker.status == "cancelled"
                assert mock_job_for_worker.finished_at is not None
                assert mock_job_for_worker.metrics is not None
                assert "cancellation_completed" in mock_job_for_worker.metrics


class TestRedisCaching:
    """Test Redis caching for cancellation flags."""
    
    @pytest.fixture
    def redis_client(self):
        """Get Redis client."""
        return get_redis_client()
    
    def test_redis_cache_set_and_get(
        self,
        cancellation_service: JobCancellationService,
        mock_job: Job,
        redis_client,
        db: Session
    ):
        """Test that cancellation flag is cached in Redis."""
        # Clear any existing cache
        cache_key = f"job:cancel:{mock_job.id}"
        redis_client.delete(cache_key)
        
        # Request cancellation (should set cache)
        asyncio.run(cancellation_service.request_cancellation(
            db=db,
            job_id=mock_job.id,
            user_id=1
        ))
        
        # Check Redis cache
        cached = redis_client.get(cache_key)
        assert cached is not None
        
        cache_data = json.loads(cached)
        assert cache_data["cancelled"] is True
        assert cache_data["requested_by"] == 1
        assert "requested_at" in cache_data
    
    def test_check_uses_redis_cache(
        self,
        cancellation_service: JobCancellationService,
        mock_job: Job,
        redis_client,
        db: Session
    ):
        """Test that check_cancellation uses Redis cache when available."""
        # Set cache directly
        cache_key = f"job:cancel:{mock_job.id}"
        redis_client.setex(
            cache_key,
            3600,
            json.dumps({
                "cancelled": True,
                "requested_at": datetime.now(timezone.utc).isoformat()
            })
        )
        
        # Check should detect cancellation from cache
        with pytest.raises(JobCancelledError):
            cancellation_service.check_cancellation(db, mock_job.id)
        
        # Job in DB is still not cancelled
        db.refresh(mock_job)
        assert mock_job.cancel_requested is False
    
    def test_fallback_to_db_when_redis_unavailable(
        self,
        cancellation_service: JobCancellationService,
        mock_job: Job,
        db: Session
    ):
        """Test fallback to database when Redis is unavailable."""
        # Mock Redis failure
        with patch.object(cancellation_service, "redis_client", None):
            # Set job as cancelled in DB
            mock_job.cancel_requested = True
            db.commit()
            
            # Should still detect cancellation from DB
            with pytest.raises(JobCancelledError):
                cancellation_service.check_cancellation(db, mock_job.id)


class TestAuditLogging:
    """Test audit logging for cancellation events."""
    
    @pytest.mark.asyncio
    async def test_cancellation_creates_audit_log(
        self,
        cancellation_service: JobCancellationService,
        mock_job: Job,
        db: Session
    ):
        """Test that cancellation creates audit log entries."""
        with patch("app.services.job_cancellation_service.AuditService") as mock_audit:
            mock_audit_instance = mock_audit.return_value
            mock_audit_instance.create_audit_entry = AsyncMock()
            
            # Request cancellation
            await cancellation_service.request_cancellation(
                db=db,
                job_id=mock_job.id,
                user_id=1,
                reason="Test cancellation",
                ip_address="192.168.1.1"
            )
            
            # Verify audit was created
            mock_audit_instance.create_audit_entry.assert_called()
            call_args = mock_audit_instance.create_audit_entry.call_args
            
            assert call_args.kwargs["event_type"] == "job.cancellation.cancel_requested"
            assert call_args.kwargs["user_id"] == 1
            assert call_args.kwargs["scope_type"] == "job"
            assert call_args.kwargs["scope_id"] == mock_job.id
            assert call_args.kwargs["ip_address"] == "192.168.1.1"
            
            payload = call_args.kwargs["payload"]
            assert payload["action"] == "cancel_requested"
            assert payload["reason"] == "Test cancellation"