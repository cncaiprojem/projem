"""
Task 7.16: WebSocket Endpoint for Real-time Progress Updates

This module provides WebSocket endpoints for:
- Real-time job progress streaming
- Authentication via JWT tokens
- Connection management and cleanup
- Progress filtering and throttling
- Automatic reconnection support
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, Optional, Set
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
    status
)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ...core.database import get_async_db
from ...core.logging import get_logger
from ...core.redis_pubsub import redis_progress_pubsub, RedisProgressPubSub
from ...models.job import Job
from ...models.user import User
from ...schemas.progress import ProgressMessageV2, ProgressSubscription
from ...services.auth_service import verify_token
from ...middleware.correlation_middleware import get_correlation_id

logger = get_logger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])

# Centralized Redis listener for scalability
class CentralizedRedisListener:
    """
    Centralized Redis pub/sub listener that dispatches to multiple WebSocket clients.
    Uses a single Redis subscription per job instead of one per connection.
    """
    
    def __init__(self):
        self.job_listeners: Dict[int, asyncio.Task] = {}
        self.lock = asyncio.Lock()
        
    async def start_job_listener(self, job_id: int, manager: 'ConnectionManager') -> None:
        """Start a centralized listener for a specific job if not already running."""
        async with self.lock:
            if job_id in self.job_listeners:
                # Listener already running for this job
                return
            
            # Create a new listener task for this job
            task = asyncio.create_task(self._job_listener(job_id, manager))
            self.job_listeners[job_id] = task
            logger.info(f"Started centralized Redis listener for job {job_id}")
    
    async def stop_job_listener(self, job_id: int) -> None:
        """Stop the listener for a specific job if no more connections need it."""
        async with self.lock:
            if job_id in self.job_listeners:
                task = self.job_listeners[job_id]
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                del self.job_listeners[job_id]
                logger.info(f"Stopped centralized Redis listener for job {job_id}")
    
    async def _job_listener(self, job_id: int, manager: 'ConnectionManager') -> None:
        """Listen to Redis pub/sub for a specific job and dispatch to all subscribed connections."""
        try:
            async with redis_progress_pubsub.subscribe_to_job(job_id) as pubsub:
                while True:
                    try:
                        message = await pubsub.get_message(
                            ignore_subscribe_messages=True,
                            timeout=1.0
                        )
                        
                        if message and message["type"] == "message":
                            try:
                                # Parse progress message
                                progress_data = json.loads(message["data"])
                                progress = ProgressMessageV2(**progress_data)
                                
                                # Get all connections subscribed to this job
                                connection_ids = manager.job_connections.get(job_id, set()).copy()
                                
                                if connection_ids:
                                    # Send to all subscribed connections concurrently
                                    await asyncio.gather(*[
                                        manager.send_to_connection(
                                            conn_id,
                                            {
                                                "type": "progress",
                                                **progress.model_dump()
                                            }
                                        )
                                        for conn_id in connection_ids
                                    ], return_exceptions=True)
                                
                                # Check if job is complete
                                if progress.status in ["completed", "failed", "cancelled"]:
                                    logger.info(f"Job {job_id} finished with status {progress.status}")
                                    break
                                    
                            except (json.JSONDecodeError, ValueError) as e:
                                logger.warning(f"Failed to parse progress message: {e}", exc_info=True)
                    
                    except asyncio.CancelledError:
                        break
                    except Exception as e:
                        logger.error(f"Redis listener error for job {job_id}: {e}", exc_info=True)
                        await asyncio.sleep(1)  # Brief pause before retry
                        
        except Exception as e:
            logger.error(f"Fatal error in job listener for job {job_id}: {e}", exc_info=True)
        finally:
            # Clean up when listener exits
            async with self.lock:
                if job_id in self.job_listeners:
                    del self.job_listeners[job_id]

# Singleton instance of centralized listener
centralized_listener = CentralizedRedisListener()

# WebSocket connection tracking
class ConnectionManager:
    """Manager for WebSocket connections."""
    
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_jobs: Dict[str, Set[int]] = {}
        self.job_connections: Dict[int, Set[str]] = {}
    
    async def connect(self, websocket: WebSocket, connection_id: str) -> None:
        """Accept and register WebSocket connection."""
        await websocket.accept()
        self.active_connections[connection_id] = websocket
        self.connection_jobs[connection_id] = set()
        logger.info(f"WebSocket connected: {connection_id}")
    
    async def disconnect(self, connection_id: str) -> None:
        """Remove WebSocket connection and clean up resources."""
        # Clean up job subscriptions and stop listeners if needed
        if connection_id in self.connection_jobs:
            # Unsubscribe from all jobs for this connection
            for job_id in list(self.connection_jobs[connection_id]):
                await self.unsubscribe_from_job(connection_id, job_id)
            del self.connection_jobs[connection_id]
        
        # Remove connection
        if connection_id in self.active_connections:
            del self.active_connections[connection_id]
        
        logger.info(f"WebSocket disconnected: {connection_id}")
    
    async def subscribe_to_job(self, connection_id: str, job_id: int) -> None:
        """Subscribe connection to job updates and start centralized listener if needed."""
        if connection_id in self.connection_jobs:
            self.connection_jobs[connection_id].add(job_id)
            if job_id not in self.job_connections:
                self.job_connections[job_id] = set()
            self.job_connections[job_id].add(connection_id)
            logger.debug(f"Connection {connection_id} subscribed to job {job_id}")
            
            # Start centralized listener for this job if not already running
            await centralized_listener.start_job_listener(job_id, self)
    
    async def unsubscribe_from_job(self, connection_id: str, job_id: int) -> None:
        """Unsubscribe connection from job updates and stop listener if no more connections."""
        if connection_id in self.connection_jobs:
            self.connection_jobs[connection_id].discard(job_id)
        if job_id in self.job_connections:
            self.job_connections[job_id].discard(connection_id)
            if not self.job_connections[job_id]:
                del self.job_connections[job_id]
                # Stop centralized listener if no more connections for this job
                await centralized_listener.stop_job_listener(job_id)
        logger.debug(f"Connection {connection_id} unsubscribed from job {job_id}")
    
    async def send_to_connection(
        self,
        connection_id: str,
        message: Dict
    ) -> bool:
        """Send message to specific connection."""
        if connection_id in self.active_connections:
            try:
                websocket = self.active_connections[connection_id]
                await websocket.send_json(message)
                return True
            except Exception as e:
                logger.warning(f"Failed to send to connection {connection_id}: {e}", exc_info=True)
                return False
        return False
    
    async def broadcast_to_job(
        self,
        job_id: int,
        message: Dict
    ) -> int:
        """Broadcast message to all connections subscribed to a job."""
        if job_id not in self.job_connections:
            return 0
        
        sent_count = 0
        for connection_id in self.job_connections[job_id].copy():
            if await self.send_to_connection(connection_id, message):
                sent_count += 1
        
        return sent_count
    
    def get_connection_count(self) -> int:
        """Get total number of active connections."""
        return len(self.active_connections)
    
    def get_job_subscriber_count(self, job_id: int) -> int:
        """Get number of subscribers for a job."""
        return len(self.job_connections.get(job_id, set()))


# Global connection manager
manager = ConnectionManager()


async def get_current_user_from_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_db)
) -> User:
    """
    Authenticate WebSocket connection via JWT token.
    
    Args:
        websocket: WebSocket connection
        token: JWT token from query parameter
        db: Database session
        
    Returns:
        Authenticated user
        
    Raises:
        WebSocketException: If authentication fails
    """
    if not token:
        # Try to get token from headers
        auth_header = websocket.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:]
    
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="No token provided")
    
    try:
        # Verify token
        payload = verify_token(token)
        user_id = payload.get("sub")
        
        if not user_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid token")
        
        # Get user from database
        result = await db.execute(
            select(User).where(User.id == int(user_id))
        )
        user = result.scalar_one_or_none()
        
        if not user or not user.is_active:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="User not found or inactive")
        
        return user
        
    except Exception as e:
        logger.warning(f"WebSocket authentication failed: {e}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Authentication failed")


@router.websocket("/jobs/{job_id}/progress")
async def websocket_job_progress(
    websocket: WebSocket,
    job_id: int,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_db)
):
    """
    WebSocket endpoint for real-time job progress updates.
    
    Authentication: JWT token via query parameter or Authorization header
    
    Message format:
    - Client -> Server: {"action": "subscribe"|"unsubscribe", "last_event_id": <optional>}
    - Server -> Client: ProgressMessageV2 as JSON
    
    Connection closes on:
    - Client disconnect
    - Authentication failure
    - Job completion
    - Server error
    """
    connection_id = str(uuid4())
    user = None
    pubsub_task = None
    
    try:
        # Authenticate user
        user = await get_current_user_from_ws(websocket, token=token, db=db)
        
        # Check job access
        result = await db.execute(
            select(Job).where(Job.id == job_id)
        )
        job = result.scalar_one_or_none()
        
        if not job:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Job not found")
        
        # Check permission (user must own the job or be admin)
        if job.user_id != user.id and user.role != "admin":
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Access denied")
        
        # Accept connection
        await manager.connect(websocket, connection_id)
        await manager.subscribe_to_job(connection_id, job_id)  # Now async with centralized listener
        
        # Send initial connection message
        await websocket.send_json({
            "type": "connection",
            "connection_id": connection_id,
            "job_id": job_id,
            "status": job.status.value,
            "progress": job.progress,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # No need for per-connection Redis listener anymore - centralized listener handles it
        
        # Handle incoming WebSocket messages
        while True:
            try:
                # Wait for client messages
                data = await websocket.receive_json()
                
                # Handle client actions
                action = data.get("action")
                
                if action == "ping":
                    # Respond to ping
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                
                elif action == "unsubscribe":
                    # Client wants to unsubscribe
                    logger.info(f"Client requested unsubscribe from job {job_id}")
                    break
                
                else:
                    logger.debug(f"Unknown action from client: {action}")
            
            except WebSocketDisconnect:
                logger.info(f"Client disconnected from job {job_id}")
                break
            except json.JSONDecodeError:
                logger.warning("Invalid JSON from client")
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format"
                })
            except Exception as e:
                logger.error(f"WebSocket error: {e}", exc_info=True)
                break
    
    except WebSocketException:
        # Already handled
        pass
    except Exception as e:
        logger.error(f"Unexpected WebSocket error: {e}", exc_info=True)
        try:
            await websocket.send_json({
                "type": "error",
                "message": "Internal server error"
            })
        except:
            pass
    
    finally:
        # Cleanup - use async disconnect which handles all unsubscriptions
        await manager.disconnect(connection_id)
        
        # Try to close WebSocket gracefully
        try:
            await websocket.close()
        except:
            pass


@router.get("/connections/stats")
async def get_connection_stats(
    current_user: User = Depends(verify_token)
):
    """
    Get WebSocket connection statistics (admin only).
    
    Returns:
        Connection statistics including total connections and job subscribers
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    
    return {
        "total_connections": manager.get_connection_count(),
        "job_subscriptions": {
            job_id: manager.get_job_subscriber_count(job_id)
            for job_id in manager.job_connections.keys()
        },
        "timestamp": datetime.now(timezone.utc).isoformat()
    }