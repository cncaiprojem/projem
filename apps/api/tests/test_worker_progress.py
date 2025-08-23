"""
Comprehensive tests for Task 6.7: Worker progress update conventions and status change events

Tests cover:
- Monotonic progress validation
- Throttling mechanism (2s window)
- Event publishing on status transitions
- ERP bridge integration
- Coalescing of rapid updates
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock, AsyncMock

import pytest
from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.enums import JobStatus
from app.services.worker_progress_service import (
    WorkerProgressService,
    ProgressValidationError
)
from app.services.event_publisher_service import EventPublisherService
from app.tasks.worker_helpers import progress, start_job, complete_job, fail_job


@pytest.fixture
def mock_db():
    """Mock database session."""
    db = Mock(spec=Session)
    return db


@pytest.fixture
def mock_job():
    """Mock job object."""
    job = Mock(spec=Job)
    job.id = 123
    job.status = JobStatus.PENDING
    job.progress = 0
    job.attempts = 1
    job.metrics = {}
    job.started_at = None
    job.finished_at = None
    return job


@pytest.fixture
def worker_progress_service():
    """Worker progress service instance."""
    return WorkerProgressService()


@pytest.fixture
def event_publisher_service():
    """Event publisher service instance."""
    return EventPublisherService()


class TestWorkerProgressService:
    """Test suite for WorkerProgressService."""
    
    @pytest.mark.asyncio
    async def test_monotonic_progress_validation(self, worker_progress_service, mock_db, mock_job):
        """Test that progress must be monotonic (never decreases)."""
        # Setup
        mock_job.progress = 50
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_job
        
        # Test decreasing progress - should fail
        with patch.object(worker_progress_service, 'event_publisher') as mock_publisher:
            mock_publisher.publish_job_status_changed = AsyncMock(return_value=True)
            
            result = await worker_progress_service.update_progress(
                mock_db, 123, 30, "test", "Testing"
            )
            
            assert result["success"] is False
            assert "cannot decrease" in result["error"].lower()
            assert mock_db.commit.call_count == 0  # Should not commit on validation failure
    
    @pytest.mark.asyncio
    async def test_progress_update_success(self, worker_progress_service, mock_db, mock_job):
        """Test successful progress update."""
        # Setup
        mock_job.progress = 25
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_job
        
        with patch.object(worker_progress_service, 'event_publisher') as mock_publisher:
            mock_publisher.publish_job_status_changed = AsyncMock(return_value=True)
            
            result = await worker_progress_service.update_progress(
                mock_db, 123, 50, "processing", "Processing data", {"items": 100}
            )
            
            assert result["success"] is True
            assert result["percent"] == 50
            assert mock_job.progress == 50
            assert mock_job.metrics["progress_step"] == "processing"
            assert mock_job.metrics["progress_message"] == "Processing data"
            assert mock_job.metrics["items"] == 100
            mock_db.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_throttling_mechanism(self, worker_progress_service, mock_db, mock_job):
        """Test that updates are throttled to max once per 2s per job."""
        # Setup Redis mock
        mock_redis = Mock()
        mock_redis.set.return_value = None  # Simulate key exists (throttled)
        mock_redis.setex.return_value = True
        mock_redis.get.return_value = None
        
        with patch.object(worker_progress_service, '_redis_client', mock_redis):
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_job
            
            result = await worker_progress_service.update_progress(
                mock_db, 123, 30, "test", "Testing"
            )
            
            assert result["success"] is True
            assert result["throttled"] is True
            assert mock_db.commit.call_count == 0  # Should not commit when throttled
    
    @pytest.mark.asyncio
    async def test_coalescing_updates(self, worker_progress_service, mock_db, mock_job):
        """Test that throttled updates are coalesced."""
        # Setup Redis mock with coalesced data
        coalesced_data = {
            "percent": 75,
            "step": "final",
            "message": "Final processing",
            "metrics": {"final": True}
        }
        
        mock_redis = Mock()
        mock_redis.set.return_value = True  # Not throttled
        mock_redis.get.return_value = json.dumps(coalesced_data)
        mock_redis.delete.return_value = True
        
        with patch.object(worker_progress_service, '_redis_client', mock_redis):
            with patch.object(worker_progress_service, 'event_publisher') as mock_publisher:
                mock_publisher.publish_job_status_changed = AsyncMock(return_value=True)
                
                mock_db.execute.return_value.scalar_one_or_none.return_value = mock_job
                
                # Update with lower progress - should use coalesced higher value
                result = await worker_progress_service.update_progress(
                    mock_db, 123, 50, "processing", "Processing"
                )
                
                assert result["success"] is True
                assert result["coalesced"] is True
                assert mock_job.progress == 75  # Used coalesced value
                assert mock_job.metrics["progress_step"] == "final"
                mock_redis.delete.assert_called_once()  # Cleared coalesced data
    
    @pytest.mark.asyncio
    async def test_status_transitions(self, worker_progress_service, mock_db, mock_job):
        """Test automatic status transitions based on progress."""
        test_cases = [
            # (initial_status, progress, expected_status)
            (JobStatus.PENDING, 0, JobStatus.QUEUED),
            (JobStatus.PENDING, 10, JobStatus.RUNNING),
            (JobStatus.QUEUED, 50, JobStatus.RUNNING),
            (JobStatus.RUNNING, 75, JobStatus.RUNNING),  # No change
        ]
        
        for initial_status, progress_val, expected_status in test_cases:
            mock_job.status = initial_status
            mock_job.progress = 0
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_job
            
            with patch.object(worker_progress_service, 'event_publisher') as mock_publisher:
                mock_publisher.publish_job_status_changed = AsyncMock(return_value=True)
                
                result = await worker_progress_service.update_progress(
                    mock_db, 123, progress_val, "test", "Testing"
                )
                
                assert result["success"] is True
                if initial_status != expected_status:
                    assert mock_job.status == expected_status
    
    @pytest.mark.asyncio
    async def test_event_publishing_on_transitions(self, worker_progress_service, mock_db, mock_job):
        """Test that events are published on status transitions."""
        mock_job.status = JobStatus.PENDING
        mock_job.progress = 0
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_job
        
        with patch.object(worker_progress_service, 'event_publisher') as mock_publisher:
            mock_publisher.publish_job_status_changed = AsyncMock(return_value=True)
            
            # Update that causes status transition
            result = await worker_progress_service.update_progress(
                mock_db, 123, 25, "processing", "Processing"
            )
            
            assert result["success"] is True
            assert result["event_published"] is True
            
            # Verify event was published with correct data
            mock_publisher.publish_job_status_changed.assert_called_once()
            call_args = mock_publisher.publish_job_status_changed.call_args
            assert call_args.kwargs["job_id"] == 123
            assert call_args.kwargs["progress"] == 25
            assert call_args.kwargs["step"] == "processing"
            assert call_args.kwargs["message"] == "Processing"
    
    @pytest.mark.asyncio
    async def test_milestone_progress_events(self, worker_progress_service, mock_db, mock_job):
        """Test that events are published at milestone percentages (0, 25, 50, 75, 100)."""
        milestones = [0, 25, 50, 75, 100]
        
        for milestone in milestones:
            mock_job.status = JobStatus.RUNNING
            mock_job.progress = milestone - 1 if milestone > 0 else 0
            mock_db.execute.return_value.scalar_one_or_none.return_value = mock_job
            
            with patch.object(worker_progress_service, 'event_publisher') as mock_publisher:
                mock_publisher.publish_job_status_changed = AsyncMock(return_value=True)
                
                result = await worker_progress_service.update_progress(
                    mock_db, 123, milestone, "milestone", f"Reached {milestone}%"
                )
                
                assert result["success"] is True
                assert result["event_published"] is True


class TestEventPublisherService:
    """Test suite for EventPublisherService."""
    
    @pytest.mark.asyncio
    async def test_event_deduplication(self, event_publisher_service):
        """Test that duplicate events are not published (exactly-once delivery)."""
        mock_redis = Mock()
        # First call returns True (not duplicate), second returns None (duplicate)
        mock_redis.set.side_effect = [True, None]
        
        with patch.object(event_publisher_service, '_redis_client', mock_redis):
            with patch.object(event_publisher_service, '_get_channel') as mock_channel:
                mock_channel.return_value.basic_publish.return_value = None
                
                # First publish - should succeed
                result1 = await event_publisher_service.publish_job_status_changed(
                    job_id=123, status="running", progress=50, attempt=1
                )
                assert result1 is True
                assert mock_channel.return_value.basic_publish.call_count == 1
                
                # Second publish with same params - should be deduplicated
                result2 = await event_publisher_service.publish_job_status_changed(
                    job_id=123, status="running", progress=50, attempt=1
                )
                assert result2 is True  # Still returns True (considered success)
                assert mock_channel.return_value.basic_publish.call_count == 1  # Not called again
    
    @pytest.mark.asyncio
    async def test_event_payload_structure(self, event_publisher_service):
        """Test that event payload has correct structure."""
        with patch.object(event_publisher_service, '_get_channel') as mock_channel:
            mock_channel.return_value.basic_publish.return_value = None
            
            await event_publisher_service.publish_job_status_changed(
                job_id=123,
                status="completed",
                progress=100,
                attempt=2,
                previous_status="running",
                previous_progress=90,
                step="finalization",
                message="Job completed successfully"
            )
            
            # Get the published message
            call_args = mock_channel.return_value.basic_publish.call_args
            body = json.loads(call_args.kwargs["body"])
            
            # Verify payload structure
            assert body["event_type"] == "job.status.changed"
            assert body["job_id"] == 123
            assert body["status"] == "completed"
            assert body["progress"] == 100
            assert body["attempt"] == 2
            assert body["previous_status"] == "running"
            assert body["previous_progress"] == 90
            assert body["step"] == "finalization"
            assert body["message"] == "Job completed successfully"
            assert "timestamp" in body
            assert "event_id" in body
    
    @pytest.mark.asyncio
    async def test_exchange_binding(self, event_publisher_service):
        """Test that events.jobs exchange is bound to ERP bridge."""
        with patch.object(event_publisher_service, '_get_channel') as mock_channel:
            # Reinitialize to trigger setup
            event_publisher_service._setup_exchanges()
            
            # Verify exchanges were declared
            assert mock_channel.return_value.exchange_declare.call_count >= 2
            
            # Verify exchange binding for ERP fanout
            mock_channel.return_value.exchange_bind.assert_called_with(
                destination="erp.outbound",
                source="events.jobs",
                routing_key="job.status.#"
            )


class TestWorkerHelpers:
    """Test suite for worker helper functions."""
    
    def test_progress_helper(self, mock_db):
        """Test the progress() helper function."""
        with patch('app.tasks.worker_helpers.worker_progress_service') as mock_service:
            mock_service.update_progress = AsyncMock(return_value={"success": True})
            
            result = progress(mock_db, 123, 50, "processing", "Processing data")
            
            assert result["success"] is True
            # Verify async function was called correctly
            assert mock_service.update_progress.called
    
    def test_start_job_helper(self, mock_db):
        """Test the start_job() helper function."""
        with patch('app.tasks.worker_helpers.progress') as mock_progress:
            mock_progress.return_value = {"success": True}
            
            result = start_job(mock_db, 123, "Starting job")
            
            mock_progress.assert_called_once_with(
                mock_db, 123,
                percent=0,
                step="startup",
                message="Starting job"
            )
    
    def test_complete_job_helper(self, mock_db):
        """Test the complete_job() helper function."""
        with patch('app.tasks.worker_helpers.force_progress') as mock_progress:
            with patch('app.tasks.worker_helpers.update_status') as mock_status:
                mock_progress.return_value = {"success": True}
                mock_status.return_value = {"success": True}
                
                output_data = {"result": "success"}
                result = complete_job(mock_db, 123, output_data, "Job done")
                
                mock_progress.assert_called_once_with(
                    mock_db, 123,
                    percent=100,
                    step="completed",
                    message="Job done"
                )
                mock_status.assert_called_once_with(
                    mock_db, 123,
                    JobStatus.COMPLETED,
                    output_data=output_data
                )
    
    def test_fail_job_helper(self, mock_db):
        """Test the fail_job() helper function."""
        with patch('app.tasks.worker_helpers.force_progress') as mock_progress:
            with patch('app.tasks.worker_helpers.update_status') as mock_status:
                mock_progress.return_value = {"success": True}
                mock_status.return_value = {"success": True}
                
                result = fail_job(
                    mock_db, 123,
                    "ERR_001", "Something went wrong",
                    progress_percent=75
                )
                
                mock_progress.assert_called_once()
                mock_status.assert_called_once_with(
                    mock_db, 123,
                    JobStatus.FAILED,
                    error_code="ERR_001",
                    error_message="Something went wrong"
                )


class TestIntegration:
    """Integration tests for the complete flow."""
    
    @pytest.mark.asyncio
    async def test_complete_job_lifecycle(self, mock_db):
        """Test complete job lifecycle with progress updates and events."""
        mock_job = Mock(spec=Job)
        mock_job.id = 456
        mock_job.status = JobStatus.PENDING
        mock_job.progress = 0
        mock_job.attempts = 1
        mock_job.metrics = {}
        mock_job.started_at = None
        mock_job.finished_at = None
        
        mock_db.execute.return_value.scalar_one_or_none.return_value = mock_job
        
        # Simulate worker using helpers
        with patch('app.tasks.worker_helpers.worker_progress_service') as mock_service:
            mock_service.update_progress = AsyncMock(return_value={"success": True})
            mock_service.update_job_status = AsyncMock(return_value={"success": True})
            
            # Start job
            start_job(mock_db, 456, "Starting processing")
            
            # Progress updates (simulating throttling)
            for i in range(10, 100, 10):
                progress(mock_db, 456, i, "processing", f"Processing {i}%")
                time.sleep(0.1)  # Simulate work
            
            # Complete job
            complete_job(mock_db, 456, {"output": "result"}, "Processing complete")
            
            # Verify multiple progress updates were made
            assert mock_service.update_progress.call_count > 0
            assert mock_service.update_job_status.called