"""
Tests for job cancellation service (Task 4.9).
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock
import uuid

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.models.job import Job
from app.models.enums import JobStatus
from app.models.license import License
from app.models.user import User
from app.services.job_cancellation_service import job_cancellation_service
from app.core.exceptions import ServiceError


@pytest.fixture
def db_session():
    """Mock database session."""
    session = Mock(spec=Session)
    session.begin_nested = Mock()
    session.commit = Mock()
    session.rollback = Mock()
    session.get = Mock()
    session.execute = Mock()
    session.query = Mock()
    return session


@pytest.fixture
def sample_user():
    """Create a sample user."""
    user = Mock(spec=User)
    user.id = 1
    user.email = "test@example.com"
    return user


@pytest.fixture
def sample_license():
    """Create a sample license."""
    license = Mock(spec=License)
    license.id = uuid.uuid4()
    license.user_id = 1
    license.status = "expired"
    license.ends_at = datetime.now(timezone.utc) - timedelta(days=1)
    return license


@pytest.fixture
def sample_jobs():
    """Create sample jobs in various states."""
    jobs = []
    
    # Running job
    job1 = Mock(spec=Job)
    job1.id = 1
    job1.user_id = 1
    job1.status = JobStatus.RUNNING
    job1.cancel_requested = False
    job1.cancellation_reason = None
    job1.type = Mock(value="cad_generate")
    jobs.append(job1)
    
    # Pending job
    job2 = Mock(spec=Job)
    job2.id = 2
    job2.user_id = 1
    job2.status = JobStatus.PENDING
    job2.cancel_requested = False
    job2.cancellation_reason = None
    job2.type = Mock(value="cam_process")
    jobs.append(job2)
    
    # Queued job
    job3 = Mock(spec=Job)
    job3.id = 3
    job3.user_id = 1
    job3.status = JobStatus.QUEUED
    job3.cancel_requested = False
    job3.cancellation_reason = None
    job3.type = Mock(value="gcode_post")
    jobs.append(job3)
    
    # Already completed job (should not be affected)
    job4 = Mock(spec=Job)
    job4.id = 4
    job4.user_id = 1
    job4.status = JobStatus.COMPLETED
    job4.cancel_requested = False
    job4.cancellation_reason = None
    job4.type = Mock(value="report_generate")
    jobs.append(job4)
    
    return jobs


@pytest.mark.asyncio
async def test_cancel_jobs_for_expired_license_success(
    db_session, sample_license, sample_jobs
):
    """Test successful job cancellation for expired license."""
    # Setup
    active_jobs = sample_jobs[:3]  # First 3 are active
    db_session.execute().scalars().all.return_value = active_jobs
    
    # Mock audit service
    with patch('app.services.job_cancellation_service.audit_service') as mock_audit:
        mock_audit.create_audit_entry = AsyncMock()
        
        # Execute
        result = await job_cancellation_service.cancel_jobs_for_expired_license(
            db=db_session,
            license_id=sample_license.id,
            user_id=1,
            reason="license_expired"
        )
    
    # Verify
    assert result["success"] is True
    assert len(result["affected_jobs"]) == 3
    assert result["immediately_cancelled"] == 2  # PENDING and QUEUED
    assert result["cancel_requested"] == 1  # RUNNING
    
    # Check that cancel_requested was set
    for job in active_jobs:
        assert job.cancel_requested is True
        assert job.cancellation_reason == "license_expired"
    
    # Check that PENDING/QUEUED were cancelled immediately
    assert sample_jobs[1].set_cancelled.called
    assert sample_jobs[2].set_cancelled.called
    
    # Check that RUNNING was not cancelled immediately
    assert not sample_jobs[0].set_cancelled.called
    
    # Check audit was created
    mock_audit.create_audit_entry.assert_called_once()
    
    # Check commit was called
    db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cancel_jobs_database_error(db_session, sample_license):
    """Test job cancellation handles database errors gracefully."""
    # Setup
    db_session.execute.side_effect = SQLAlchemyError("Database connection lost")
    
    # Execute and verify exception
    with pytest.raises(ServiceError) as exc_info:
        await job_cancellation_service.cancel_jobs_for_expired_license(
            db=db_session,
            license_id=sample_license.id,
            user_id=1,
            reason="license_expired"
        )
    
    assert exc_info.value.code == "JOB_CANCELLATION_ERROR"
    assert "İş iptali sırasında hata oluştu" in exc_info.value.message
    
    # Check rollback was called
    db_session.rollback.assert_called_once()


def test_check_cancel_requested_true(db_session):
    """Test checking if cancellation is requested returns True."""
    # Setup
    job = Mock(spec=Job)
    job.cancel_requested = True
    db_session.get.return_value = job
    
    # Execute
    result = job_cancellation_service.check_cancel_requested(db_session, 1)
    
    # Verify
    assert result is True
    db_session.get.assert_called_once_with(Job, 1)


def test_check_cancel_requested_false(db_session):
    """Test checking if cancellation is requested returns False."""
    # Setup
    job = Mock(spec=Job)
    job.cancel_requested = False
    db_session.get.return_value = job
    
    # Execute
    result = job_cancellation_service.check_cancel_requested(db_session, 1)
    
    # Verify
    assert result is False


def test_check_cancel_requested_job_not_found(db_session):
    """Test checking cancellation for non-existent job."""
    # Setup
    db_session.get.return_value = None
    
    # Execute
    result = job_cancellation_service.check_cancel_requested(db_session, 999)
    
    # Verify
    assert result is False


def test_get_impacted_jobs_for_license(db_session, sample_license, sample_jobs):
    """Test retrieving impacted jobs for a license."""
    # Setup
    db_session.get.return_value = sample_license
    
    # Mock query for impacted jobs
    impacted_jobs = [sample_jobs[0], sample_jobs[1]]  # Two impacted jobs
    for job in impacted_jobs:
        job.cancellation_reason = "license_expired"
        job.cancel_requested = True
        job.created_at = datetime.now(timezone.utc)
        job.started_at = datetime.now(timezone.utc)
        job.finished_at = None
        job.progress = 50
    
    mock_query = Mock()
    mock_query.scalars().all.return_value = impacted_jobs
    db_session.execute.return_value = mock_query
    
    # Execute
    result = job_cancellation_service.get_impacted_jobs_for_license(
        db=db_session,
        license_id=sample_license.id
    )
    
    # Verify
    assert len(result) == 2
    assert result[0]["id"] == 1
    assert result[0]["cancellation_reason"] == "license_expired"
    assert result[0]["cancel_requested"] is True
    assert result[1]["id"] == 2


def test_get_impacted_jobs_license_not_found(db_session):
    """Test retrieving impacted jobs when license doesn't exist."""
    # Setup
    db_session.get.return_value = None
    
    # Execute
    result = job_cancellation_service.get_impacted_jobs_for_license(
        db=db_session,
        license_id=uuid.uuid4()
    )
    
    # Verify
    assert result == []


@pytest.mark.asyncio
async def test_handle_checkpoint_continue(db_session):
    """Test checkpoint handling when job should continue."""
    # Setup
    job = Mock(spec=Job)
    job.cancel_requested = False
    job.is_complete = False
    job.metrics = {}
    db_session.get.return_value = job
    
    # Execute
    result = await job_cancellation_service.handle_checkpoint(
        db=db_session,
        job_id=1,
        checkpoint_data={"step": 5, "progress": 50}
    )
    
    # Verify
    assert result is True  # Job should continue
    assert "checkpoint_data" in job.metrics
    assert job.metrics["checkpoint_data"]["step"] == 5
    db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_handle_checkpoint_cancel(db_session):
    """Test checkpoint handling when job should be cancelled."""
    # Setup
    job = Mock(spec=Job)
    job.cancel_requested = True
    job.cancellation_reason = "license_expired"
    job.is_complete = False
    job.metrics = {}
    job.set_cancelled = Mock()
    db_session.get.return_value = job
    
    # Execute
    result = await job_cancellation_service.handle_checkpoint(
        db=db_session,
        job_id=1,
        checkpoint_data={"step": 5, "progress": 50}
    )
    
    # Verify
    assert result is False  # Job should stop
    assert "last_checkpoint" in job.metrics
    job.set_cancelled.assert_called_once_with("license_expired")
    db_session.commit.assert_called_once()


@pytest.mark.asyncio
async def test_handle_checkpoint_job_not_found(db_session):
    """Test checkpoint handling when job doesn't exist."""
    # Setup
    db_session.get.return_value = None
    
    # Execute
    result = await job_cancellation_service.handle_checkpoint(
        db=db_session,
        job_id=999
    )
    
    # Verify
    assert result is False  # Job should stop


@pytest.mark.asyncio
async def test_handle_checkpoint_already_complete(db_session):
    """Test checkpoint handling when job is already complete."""
    # Setup
    job = Mock(spec=Job)
    job.is_complete = True
    job.status = JobStatus.COMPLETED
    db_session.get.return_value = job
    
    # Execute
    result = await job_cancellation_service.handle_checkpoint(
        db=db_session,
        job_id=1
    )
    
    # Verify
    assert result is False  # Job should stop