"""
Task 7.16: Server-Sent Events (SSE) Endpoint for Real-time Progress Updates

This module provides SSE endpoints as an alternative to WebSocket for:
- Real-time job progress streaming via HTTP
- Automatic reconnection with last_event_id
- Progress filtering and event resumption
- Graceful degradation for polling fallback
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Header,
    Query,
    Request,
    Response,
    status
)
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from ...core.database import get_async_db
from ...core.logging import get_logger
from ...core.redis_pubsub import redis_progress_pubsub
from ...models.job import Job
from ...models.user import User
from ...models.enums import JobStatus
from ...schemas.progress import ProgressMessageV2, EventType
from ...services.auth_service import get_current_user
from ...middleware.correlation_middleware import get_correlation_id

logger = get_logger(__name__)

# Terminal job statuses - jobs in these states will not receive further updates
TERMINAL_STATUSES = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.TIMEOUT.value
}

router = APIRouter(prefix="/api/v1/jobs", tags=["sse", "progress"])


async def progress_event_generator(
    job_id: int,
    user: User,
    db: AsyncSession,
    last_event_id: Optional[int] = None,
    filter_types: Optional[str] = None,
    milestones_only: bool = False
) -> AsyncGenerator[dict, None]:
    """
    Generate SSE events for job progress.
    
    Args:
        job_id: Job ID to stream progress for
        user: Authenticated user
        db: Database session
        last_event_id: Last event ID for resumption
        filter_types: Comma-separated event types to filter
        milestones_only: Only send milestone events
        
    Yields:
        SSE event dictionaries
    """
    # Parse filter types
    event_filter = None
    if filter_types:
        try:
            event_filter = [EventType(t.strip()) for t in filter_types.split(",")]
        except ValueError as e:
            logger.warning(f"Invalid filter types: {e}")
    
    # Check job access
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        yield {
            "event": "error",
            "data": json.dumps({"error": "Job not found"}),
            "id": "0"
        }
        return
    
    # Check permission
    if job.user_id != user.id and user.role != "admin":
        yield {
            "event": "error",
            "data": json.dumps({"error": "Access denied"}),
            "id": "0"
        }
        return
    
    # Send initial status event
    current_event_id = last_event_id + 1 if last_event_id else 1
    initial_event = {
        "event": "status",
        "data": json.dumps({
            "job_id": job_id,
            "status": job.status.value,
            "progress": job.progress,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }),
        "id": str(current_event_id)
    }
    yield initial_event
    current_event_id += 1
    
    # CRITICAL FIX: Fetch and send missed events BEFORE subscribing to new events
    if last_event_id is not None:
        try:
            # Get missed events from cache
            missed_events = await redis_progress_pubsub.get_missed_events(job_id, last_event_id)
            
            # Send missed events to client, applying filters
            for event_json in missed_events:
                try:
                    progress_data = json.loads(event_json)
                    progress = ProgressMessageV2(**progress_data)
                    
                    # Apply the same filters as for new events
                    if milestones_only and not progress.milestone:
                        continue
                    
                    if event_filter and progress.event_type not in event_filter:
                        continue
                    
                    # Send the missed event to the client
                    sse_event = {
                        "event": "progress",
                        "data": progress.model_dump_json(),
                        "id": str(progress.event_id)
                    }
                    yield sse_event
                    
                    # Update current event ID
                    if progress.event_id:
                        current_event_id = max(current_event_id, progress.event_id + 1)
                    
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning(f"Failed to parse missed event: {e}")
                    
        except Exception as e:
            logger.warning(f"Failed to fetch missed events: {e}", exc_info=True)
    
    # Subscribe to Redis pub/sub for new events (no last_event_id needed anymore)
    try:
        async with redis_progress_pubsub.subscribe_to_job(job_id) as pubsub:
            
            # Send keepalive every 30 seconds
            last_keepalive = asyncio.get_running_loop().time()
            keepalive_interval = 30.0
            
            while True:
                try:
                    # Check for progress message (no need for nested wait_for)
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0
                    )
                    
                    if message and message["type"] == "message":
                        try:
                            # Parse progress message
                            progress_data = json.loads(message["data"])
                            progress = ProgressMessageV2(**progress_data)
                            
                            # Apply filters
                            if milestones_only and not progress.milestone:
                                continue
                            
                            if event_filter and progress.event_type not in event_filter:
                                continue
                            
                            # Send SSE event
                            sse_event = {
                                "event": "progress",
                                "data": progress.model_dump_json(),
                                "id": str(progress.event_id)
                            }
                            yield sse_event
                            
                            # Check if job is complete
                            if progress.status in TERMINAL_STATUSES:
                                # Send final event
                                final_event = {
                                    "event": "complete",
                                    "data": json.dumps({
                                        "job_id": job_id,
                                        "status": progress.status,
                                        "timestamp": datetime.now(timezone.utc).isoformat()
                                    }),
                                    "id": str(progress.event_id + 1)
                                }
                                yield final_event
                                break
                        
                        except (json.JSONDecodeError, ValueError) as e:
                            logger.warning(f"Failed to parse progress message: {e}", exc_info=True)
                    
                    # Send keepalive if needed
                    current_time = asyncio.get_running_loop().time()
                    if current_time - last_keepalive > keepalive_interval:
                        keepalive_event = {
                            "event": "keepalive",
                            "data": json.dumps({"timestamp": datetime.now(timezone.utc).isoformat()}),
                            "retry": 1000  # Retry after 1 second
                        }
                        yield keepalive_event
                        last_keepalive = current_time
                
                except asyncio.CancelledError:
                    logger.info(f"SSE stream cancelled for job {job_id}")
                    break
                
                except Exception as e:
                    logger.error(f"SSE stream error: {e}", exc_info=True)
                    error_event = {
                        "event": "error",
                        "data": json.dumps({"error": str(e)}),
                        "retry": 5000  # Retry after 5 seconds
                    }
                    yield error_event
                    break
    
    except Exception as e:
        logger.error(f"Failed to subscribe to Redis: {e}", exc_info=True)
        yield {
            "event": "error",
            "data": json.dumps({"error": "Streaming service unavailable"}),
            "retry": 10000  # Retry after 10 seconds
        }


@router.get("/{job_id}/progress/stream")
async def stream_job_progress(
    job_id: int,
    request: Request,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    last_event_id: Optional[str] = Header(None),
    filter_types: Optional[str] = Query(None, description="Comma-separated event types to filter"),
    milestones_only: bool = Query(False, description="Only send milestone events")
):
    """
    Stream job progress updates via Server-Sent Events (SSE).
    
    This endpoint provides real-time progress updates for a job using SSE,
    which is compatible with browsers and supports automatic reconnection.
    
    Features:
    - Automatic reconnection with last_event_id header
    - Event filtering by type
    - Milestone-only mode for reduced traffic
    - Keepalive messages every 30 seconds
    
    Authentication: Bearer token required
    
    Event types:
    - status: Initial job status
    - progress: Progress update (ProgressMessageV2)
    - complete: Job completion
    - error: Error occurred
    - keepalive: Connection keepalive
    
    Query parameters:
    - filter_types: Comma-separated list of event types to include
    - milestones_only: Only send milestone events (phase start/end)
    
    Headers:
    - Last-Event-ID: Resume from this event ID after reconnection
    
    Returns:
        SSE event stream
    """
    # Parse last_event_id
    last_id = None
    if last_event_id:
        try:
            last_id = int(last_event_id)
        except ValueError:
            logger.warning(f"Invalid last_event_id: {last_event_id}", exc_info=True)
    
    # Create event generator
    event_generator = progress_event_generator(
        job_id=job_id,
        user=current_user,
        db=db,
        last_event_id=last_id,
        filter_types=filter_types,
        milestones_only=milestones_only
    )
    
    # Return SSE response
    return EventSourceResponse(
        event_generator,
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
            "Connection": "keep-alive",
        }
    )


@router.get("/{job_id}/progress")
async def get_job_progress_snapshot(
    job_id: int,
    db: AsyncSession = Depends(get_async_db),
    current_user: User = Depends(get_current_user),
    include_recent: bool = Query(False, description="Include recent progress events")
):
    """
    Get current job progress snapshot (polling fallback).
    
    This endpoint provides a snapshot of the current job progress,
    useful as a fallback when SSE/WebSocket is not available.
    
    Args:
        job_id: Job ID
        include_recent: Include last 10 progress events from cache
        
    Returns:
        Current job progress snapshot
    """
    # Check job access
    result = await db.execute(
        select(Job).where(Job.id == job_id)
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found"
        )
    
    # Check permission
    if job.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    response = {
        "job_id": job_id,
        "status": job.status.value,
        "progress": job.progress,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    # Include recent events if requested
    if include_recent:
        try:
            # Get recent events from Redis cache using public method
            events = await redis_progress_pubsub.get_recent_events_from_cache(
                job_id,
                count=10
            )
            
            recent_events = []
            for event_json in events:
                try:
                    event_data = json.loads(event_json)
                    recent_events.append(event_data)
                except json.JSONDecodeError:
                    logger.debug(f"Failed to parse event JSON: {event_json[:100]}...")
            
            response["recent_events"] = recent_events
        except Exception as e:
            logger.warning(f"Failed to get recent events: {e}", exc_info=True)
            response["recent_events"] = []
    
    return response