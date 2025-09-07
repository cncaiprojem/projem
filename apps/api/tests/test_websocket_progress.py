"""
Task 7.16: Tests for WebSocket and SSE Progress Updates

This module tests:
- WebSocket connection and authentication
- SSE streaming and reconnection
- Progress message format and validation
- Throttling and milestone events
- Error handling and cleanup
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from websocket import create_connection

from app.core.redis_pubsub import redis_progress_pubsub
from app.models.job import Job
from app.models.enums import JobStatus, JobType
from app.models.user import User
from app.schemas.progress import (
    ProgressMessageV2,
    EventType,
    Phase,
    OperationGroup,
    DocumentPhase,
    Assembly4Phase,
    MaterialPhase,
    OCCTOperation,
    TopologyPhase,
    ExportFormat
)
from app.services.progress_service import progress_service


@pytest.fixture
async def mock_job(async_session: AsyncSession, test_user: User):
    """Create a test job."""
    job = Job(
        user_id=test_user.id,
        type=JobType.MODEL,
        status=JobStatus.PROCESSING,
        params={"test": "params"},
        progress=0
    )
    async_session.add(job)
    await async_session.commit()
    await async_session.refresh(job)
    return job


@pytest.fixture
async def auth_token(test_user: User):
    """Create authentication token."""
    from ..app.services.auth_service import create_access_token
    
    return create_access_token(
        data={"sub": str(test_user.id)},
        expires_delta=timedelta(minutes=30)
    )


class TestWebSocketProgress:
    """Test WebSocket progress updates."""
    
    @pytest.mark.asyncio
    async def test_websocket_connection_success(
        self,
        client: TestClient,
        mock_job: Job,
        auth_token: str
    ):
        """Test successful WebSocket connection."""
        with client.websocket_connect(
            f"/ws/jobs/{mock_job.id}/progress?token={auth_token}"
        ) as websocket:
            # Should receive initial connection message
            data = websocket.receive_json()
            assert data["type"] == "connection"
            assert data["job_id"] == mock_job.id
            assert data["status"] == JobStatus.PROCESSING.value
            assert data["progress"] == 0
    
    @pytest.mark.asyncio
    async def test_websocket_authentication_failure(
        self,
        client: TestClient,
        mock_job: Job
    ):
        """Test WebSocket authentication failure."""
        with pytest.raises(Exception):
            with client.websocket_connect(
                f"/ws/jobs/{mock_job.id}/progress"
            ) as websocket:
                # Should fail without token
                pass
    
    @pytest.mark.asyncio
    async def test_websocket_progress_updates(
        self,
        client: TestClient,
        mock_job: Job,
        auth_token: str
    ):
        """Test receiving progress updates via WebSocket."""
        with client.websocket_connect(
            f"/ws/jobs/{mock_job.id}/progress?token={auth_token}"
        ) as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Publish progress update
            progress = ProgressMessageV2(
                job_id=mock_job.id,
                event_id=1,
                event_type=EventType.PROGRESS_UPDATE,
                progress_pct=50,
                message="Processing...",
                timestamp=datetime.now(timezone.utc)
            )
            
            # Simulate progress publish
            await redis_progress_pubsub.publish_progress(
                mock_job.id,
                progress
            )
            
            # Should receive progress update
            data = websocket.receive_json(timeout=5)
            assert data["type"] == "progress"
            assert data["job_id"] == mock_job.id
            assert data["progress_pct"] == 50
            assert data["message"] == "Processing..."
    
    @pytest.mark.asyncio
    async def test_websocket_milestone_events(
        self,
        client: TestClient,
        mock_job: Job,
        auth_token: str
    ):
        """Test milestone events bypass throttling."""
        with client.websocket_connect(
            f"/ws/jobs/{mock_job.id}/progress?token={auth_token}"
        ) as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Publish multiple milestone events rapidly
            for i in range(3):
                progress = ProgressMessageV2(
                    job_id=mock_job.id,
                    event_id=i + 1,
                    event_type=EventType.PHASE,
                    phase=Phase.START,
                    milestone=True,
                    message=f"Milestone {i + 1}",
                    timestamp=datetime.now(timezone.utc)
                )
                
                await redis_progress_pubsub.publish_progress(
                    mock_job.id,
                    progress,
                    force=True
                )
            
            # Should receive all milestone events despite rapid publishing
            for i in range(3):
                data = websocket.receive_json(timeout=5)
                assert data["type"] == "progress"
                assert data["milestone"] is True
                assert f"Milestone {i + 1}" in data["message"]
    
    @pytest.mark.asyncio
    async def test_websocket_freecad_progress(
        self,
        client: TestClient,
        mock_job: Job,
        auth_token: str
    ):
        """Test FreeCAD-specific progress events."""
        with client.websocket_connect(
            f"/ws/jobs/{mock_job.id}/progress?token={auth_token}"
        ) as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Test Assembly4 progress
            await progress_service.publish_assembly4_progress(
                job_id=mock_job.id,
                phase=Assembly4Phase.SOLVER_PROGRESS,
                constraints_resolved=5,
                constraints_total=10,
                iteration=3,
                residual=0.001
            )
            
            data = websocket.receive_json(timeout=5)
            assert data["type"] == "progress"
            assert data["event_type"] == EventType.ASSEMBLY4.value
            assert data["constraints_resolved"] == 5
            assert data["constraints_total"] == 10
            assert data["iteration"] == 3
            
            # Test OCCT operation progress
            await progress_service.publish_occt_progress(
                job_id=mock_job.id,
                operation=OCCTOperation.BOOLEAN_FUSE,
                phase=Phase.PROGRESS,
                shapes_done=3,
                shapes_total=5
            )
            
            data = websocket.receive_json(timeout=5)
            assert data["type"] == "progress"
            assert data["event_type"] == EventType.OCCT.value
            assert data["occt_op"] == OCCTOperation.BOOLEAN_FUSE.value
            assert data["shapes_done"] == 3
            assert data["shapes_total"] == 5
    
    @pytest.mark.asyncio
    async def test_websocket_disconnection(
        self,
        client: TestClient,
        mock_job: Job,
        auth_token: str
    ):
        """Test WebSocket disconnection handling."""
        with client.websocket_connect(
            f"/ws/jobs/{mock_job.id}/progress?token={auth_token}"
        ) as websocket:
            # Skip connection message
            websocket.receive_json()
            
            # Send unsubscribe action
            websocket.send_json({"action": "unsubscribe"})
            
            # Connection should close
            with pytest.raises(Exception):
                websocket.receive_json(timeout=1)


class TestSSEProgress:
    """Test Server-Sent Events progress updates."""
    
    @pytest.mark.asyncio
    async def test_sse_stream_success(
        self,
        async_client: AsyncClient,
        mock_job: Job,
        auth_headers: Dict[str, str]
    ):
        """Test successful SSE stream connection."""
        async with async_client.stream(
            "GET",
            f"/api/v1/jobs/{mock_job.id}/progress/stream",
            headers=auth_headers
        ) as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers["content-type"]
            
            # Read initial status event
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    assert "status" in line
                    break
    
    @pytest.mark.asyncio
    async def test_sse_reconnection(
        self,
        async_client: AsyncClient,
        mock_job: Job,
        auth_headers: Dict[str, str]
    ):
        """Test SSE reconnection with last_event_id."""
        # Simulate some events already sent
        for i in range(5):
            progress = ProgressMessageV2(
                job_id=mock_job.id,
                event_id=i + 1,
                event_type=EventType.PROGRESS_UPDATE,
                progress_pct=i * 20,
                message=f"Step {i + 1}",
                timestamp=datetime.now(timezone.utc)
            )
            await redis_progress_pubsub.cache_progress_event(
                mock_job.id,
                progress
            )
        
        # Connect with last_event_id
        headers = {**auth_headers, "Last-Event-ID": "3"}
        
        async with async_client.stream(
            "GET",
            f"/api/v1/jobs/{mock_job.id}/progress/stream",
            headers=headers
        ) as response:
            assert response.status_code == 200
            
            # Should receive events after event_id=3
            event_ids = []
            async for line in response.aiter_lines():
                if line.startswith("id:"):
                    event_id = int(line.split(":")[1].strip())
                    event_ids.append(event_id)
                    if len(event_ids) >= 2:
                        break
            
            # Should have received events 4 and 5
            assert 4 in event_ids
            assert 5 in event_ids
    
    @pytest.mark.asyncio
    async def test_sse_filtering(
        self,
        async_client: AsyncClient,
        mock_job: Job,
        auth_headers: Dict[str, str]
    ):
        """Test SSE event filtering."""
        # Request only Assembly4 events
        params = {
            "filter_types": "assembly4,occt",
            "milestones_only": False
        }
        
        async with async_client.stream(
            "GET",
            f"/api/v1/jobs/{mock_job.id}/progress/stream",
            headers=auth_headers,
            params=params
        ) as response:
            assert response.status_code == 200
            
            # Publish different event types
            await progress_service.publish_assembly4_progress(
                job_id=mock_job.id,
                phase=Assembly4Phase.SOLVER_START,
                constraints_total=10
            )
            
            await progress_service.publish_generic_progress(
                job_id=mock_job.id,
                progress_pct=50,
                message="Generic progress"
            )
            
            await progress_service.publish_occt_progress(
                job_id=mock_job.id,
                operation=OCCTOperation.FILLET,
                phase=Phase.START,
                edges_total=20
            )
            
            # Collect events
            events = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    data = json.loads(line[5:])
                    events.append(data["event_type"])
                    if len(events) >= 2:
                        break
            
            # Should only have Assembly4 and OCCT events
            assert EventType.ASSEMBLY4.value in events
            assert EventType.OCCT.value in events
            assert EventType.PROGRESS_UPDATE.value not in events
    
    @pytest.mark.asyncio
    async def test_sse_keepalive(
        self,
        async_client: AsyncClient,
        mock_job: Job,
        auth_headers: Dict[str, str]
    ):
        """Test SSE keepalive messages."""
        async with async_client.stream(
            "GET",
            f"/api/v1/jobs/{mock_job.id}/progress/stream",
            headers=auth_headers,
            timeout=35  # Wait for keepalive
        ) as response:
            assert response.status_code == 200
            
            # Wait for keepalive event (sent every 30 seconds)
            start_time = time.time()
            async for line in response.aiter_lines():
                if line.startswith("event:") and "keepalive" in line:
                    elapsed = time.time() - start_time
                    assert elapsed >= 30
                    break
    
    @pytest.mark.asyncio
    async def test_progress_snapshot_fallback(
        self,
        async_client: AsyncClient,
        mock_job: Job,
        auth_headers: Dict[str, str]
    ):
        """Test polling fallback endpoint."""
        # Add some progress events to cache
        for i in range(3):
            progress = ProgressMessageV2(
                job_id=mock_job.id,
                event_id=i + 1,
                event_type=EventType.PROGRESS_UPDATE,
                progress_pct=(i + 1) * 30,
                message=f"Step {i + 1}",
                timestamp=datetime.now(timezone.utc)
            )
            await redis_progress_pubsub.cache_progress_event(
                mock_job.id,
                progress
            )
        
        # Get snapshot with recent events
        response = await async_client.get(
            f"/api/v1/jobs/{mock_job.id}/progress",
            headers=auth_headers,
            params={"include_recent": True}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["job_id"] == mock_job.id
        assert data["status"] == JobStatus.PROCESSING.value
        assert "recent_events" in data
        assert len(data["recent_events"]) == 3
        
        # Check events are in reverse order (most recent first)
        assert data["recent_events"][0]["progress_pct"] == 90
        assert data["recent_events"][1]["progress_pct"] == 60
        assert data["recent_events"][2]["progress_pct"] == 30


class TestProgressThrottling:
    """Test progress update throttling."""
    
    @pytest.mark.asyncio
    async def test_throttling_non_milestone_events(self):
        """Test that non-milestone events are throttled."""
        job_id = 123
        published_count = 0
        
        # Publish 10 events rapidly
        for i in range(10):
            progress = ProgressMessageV2(
                job_id=job_id,
                event_id=i + 1,
                event_type=EventType.PROGRESS_UPDATE,
                progress_pct=i * 10,
                message=f"Progress {i}",
                milestone=False,
                timestamp=datetime.now(timezone.utc)
            )
            
            success = await redis_progress_pubsub.publish_progress(
                job_id,
                progress
            )
            
            if success:
                published_count += 1
            
            # Small delay to test throttling
            await asyncio.sleep(0.1)
        
        # Should have throttled some events (not all 10 published)
        assert published_count < 10
    
    @pytest.mark.asyncio
    async def test_milestone_events_bypass_throttle(self):
        """Test that milestone events bypass throttling."""
        job_id = 124
        published_count = 0
        
        # Publish 10 milestone events rapidly
        for i in range(10):
            progress = ProgressMessageV2(
                job_id=job_id,
                event_id=i + 1,
                event_type=EventType.PHASE,
                phase=Phase.START if i % 2 == 0 else Phase.END,
                milestone=True,
                message=f"Milestone {i}",
                timestamp=datetime.now(timezone.utc)
            )
            
            success = await redis_progress_pubsub.publish_progress(
                job_id,
                progress,
                force=True
            )
            
            if success:
                published_count += 1
        
        # All milestone events should be published
        assert published_count == 10


class TestProgressReporter:
    """Test worker progress reporter."""
    
    def test_progress_reporter_context_manager(self):
        """Test progress reporter operation context manager."""
        from ..app.workers.progress_reporter import WorkerProgressReporter
        
        reporter = WorkerProgressReporter()
        
        # Mock job_id retrieval
        reporter._get_job_id = MagicMock(return_value=123)
        
        with reporter.operation("Test Operation", OperationGroup.GENERAL, 10) as op:
            assert op.name == "Test Operation"
            assert op.group == OperationGroup.GENERAL
            assert op.total_steps == 10
            
            # Update progress
            op.update(5, "Halfway there")
            assert op.current_step == 5
    
    def test_progress_reporter_freecad_events(self):
        """Test FreeCAD-specific progress reporting."""
        from ..app.workers.progress_reporter import WorkerProgressReporter
        
        reporter = WorkerProgressReporter()
        reporter._get_job_id = MagicMock(return_value=123)
        reporter.update_celery_state = MagicMock()
        
        # Test document progress
        reporter.report_freecad_document(
            phase=DocumentPhase.RECOMPUTE_START,
            document_id="doc123",
            document_label="TestDoc"
        )
        
        # Check Celery state was updated
        reporter.update_celery_state.assert_called_once()
        meta = reporter.update_celery_state.call_args[1]["meta"]
        assert meta["event_type"] == EventType.DOCUMENT.value
        assert meta["subphase"] == DocumentPhase.RECOMPUTE_START.value
        
        # Test Assembly4 progress
        reporter.report_assembly4(
            phase=Assembly4Phase.SOLVER_PROGRESS,
            constraints_resolved=5,
            constraints_total=10,
            iteration=3,
            residual=0.001
        )
        
        # Check progress percentage calculated
        meta = reporter.update_celery_state.call_args[1]["meta"]
        assert meta["progress_pct"] == 50