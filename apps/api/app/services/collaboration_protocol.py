"""
Collaboration Protocol for Real-time FreeCAD Model Synchronization.
Manages WebSocket connections, operation queues, and conflict resolution.
"""

import asyncio
import json
import logging
from datetime import datetime, UTC, timedelta
from typing import Dict, List, Set, Optional, Any, Callable
from collections import defaultdict, deque
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect
from redis import asyncio as aioredis

from app.services.operational_transform import (
    OperationalTransform,
    ModelOperation,
    ConflictResolutionStrategy,
    TransformResult,
    OperationType
)
from app.services.conflict_resolver import ConflictResolver
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class CollaborationSession:
    """Represents a collaboration session for a FreeCAD document."""
    document_id: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    participants: Set[str] = field(default_factory=set)
    operation_version: int = 0
    operation_history: deque = field(default_factory=lambda: deque(maxlen=1000))
    pending_operations: Dict[str, List[ModelOperation]] = field(default_factory=dict)
    conflict_queue: List[Dict[str, Any]] = field(default_factory=list)
    
    def add_participant(self, user_id: str):
        """Add a participant to the session."""
        self.participants.add(user_id)
    
    def remove_participant(self, user_id: str):
        """Remove a participant from the session."""
        self.participants.discard(user_id)
    
    def is_empty(self) -> bool:
        """Check if session has no participants."""
        return len(self.participants) == 0
    
    def increment_version(self) -> int:
        """Increment and return the operation version."""
        self.operation_version += 1
        return self.operation_version


@dataclass
class WebSocketConnection:
    """Represents a WebSocket connection for a user."""
    websocket: WebSocket
    user_id: str
    session_id: str
    document_id: str
    connected_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))
    pending_acks: Set[str] = field(default_factory=set)
    
    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.now(UTC)


class WebSocketManager:
    """Manages WebSocket connections for collaborative editing."""
    
    def __init__(self):
        self.connections: Dict[str, WebSocketConnection] = {}
        self.document_connections: Dict[str, Set[str]] = defaultdict(set)
        self.user_connections: Dict[str, Set[str]] = defaultdict(set)
        
    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        document_id: str,
        session_id: str
    ) -> str:
        """
        Connect a new WebSocket client.
        
        Returns:
            Connection ID
        """
        await websocket.accept()
        
        connection_id = str(uuid.uuid4())
        connection = WebSocketConnection(
            websocket=websocket,
            user_id=user_id,
            session_id=session_id,
            document_id=document_id
        )
        
        self.connections[connection_id] = connection
        self.document_connections[document_id].add(connection_id)
        self.user_connections[user_id].add(connection_id)
        
        logger.info(f"WebSocket connected: user={user_id}, document={document_id}, connection={connection_id}")
        
        return connection_id
    
    async def disconnect(self, connection_id: str):
        """Disconnect a WebSocket client."""
        if connection_id not in self.connections:
            return
        
        connection = self.connections[connection_id]
        
        # Remove from tracking structures
        self.document_connections[connection.document_id].discard(connection_id)
        self.user_connections[connection.user_id].discard(connection_id)
        
        # Clean up empty entries
        if not self.document_connections[connection.document_id]:
            del self.document_connections[connection.document_id]
        if not self.user_connections[connection.user_id]:
            del self.user_connections[connection.user_id]
        
        del self.connections[connection_id]
        
        logger.info(f"WebSocket disconnected: connection={connection_id}")
    
    async def send_to_connection(self, connection_id: str, message: Dict[str, Any]):
        """Send message to specific connection."""
        if connection_id not in self.connections:
            return
        
        connection = self.connections[connection_id]
        try:
            await connection.websocket.send_json(message)
            connection.update_activity()
        except Exception as e:
            logger.error(f"Error sending to connection {connection_id}: {e}")
            await self.disconnect(connection_id)
    
    async def broadcast_to_document(
        self,
        document_id: str,
        message: Dict[str, Any],
        exclude: Optional[Set[str]] = None
    ):
        """Broadcast message to all connections for a document."""
        exclude = exclude or set()
        connection_ids = self.document_connections.get(document_id, set())
        
        for conn_id in connection_ids:
            if conn_id not in exclude:
                await self.send_to_connection(conn_id, message)
    
    async def send_to_user(self, user_id: str, message: Dict[str, Any]):
        """Send message to all connections for a user."""
        connection_ids = self.user_connections.get(user_id, set())
        
        for conn_id in connection_ids:
            await self.send_to_connection(conn_id, message)
    
    def get_document_users(self, document_id: str) -> Set[str]:
        """Get all users connected to a document."""
        users = set()
        for conn_id in self.document_connections.get(document_id, set()):
            if conn_id in self.connections:
                users.add(self.connections[conn_id].user_id)
        return users
    
    async def ping_connections(self):
        """Ping all connections to keep them alive."""
        for conn_id, connection in list(self.connections.items()):
            # Check for timeout
            if datetime.now(UTC) - connection.last_activity > timedelta(minutes=5):
                logger.warning(f"Connection {conn_id} timed out")
                await self.disconnect(conn_id)
            else:
                await self.send_to_connection(conn_id, {"type": "ping"})


class OperationQueue:
    """Manages operation queuing and ordering."""
    
    def __init__(self, max_size: int = 10000):
        self.queue: deque = deque(maxlen=max_size)
        self.processing: Dict[str, ModelOperation] = {}
        self.processed: Set[str] = set()
        
    def enqueue(self, operation: ModelOperation):
        """Add operation to queue."""
        if operation.id not in self.processed:
            self.queue.append(operation)
    
    def dequeue(self) -> Optional[ModelOperation]:
        """Get next operation from queue."""
        if self.queue:
            operation = self.queue.popleft()
            self.processing[operation.id] = operation
            return operation
        return None
    
    def mark_processed(self, operation_id: str):
        """Mark operation as processed."""
        if operation_id in self.processing:
            del self.processing[operation_id]
        self.processed.add(operation_id)
    
    def get_pending_count(self) -> int:
        """Get count of pending operations."""
        return len(self.queue)
    
    def get_processing_count(self) -> int:
        """Get count of processing operations."""
        return len(self.processing)
    
    def clear(self):
        """Clear all queues."""
        self.queue.clear()
        self.processing.clear()
        self.processed.clear()


class CollaborationProtocol:
    """
    Main collaboration protocol handler.
    Coordinates WebSocket communication, operation transformation, and conflict resolution.
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        self.websocket_manager = WebSocketManager()
        self.operation_transform = OperationalTransform()
        self.conflict_resolver = ConflictResolver()
        self.sessions: Dict[str, CollaborationSession] = {}
        self.operation_queues: Dict[str, OperationQueue] = {}
        self.redis_url = redis_url or settings.REDIS_URL
        self.redis_client: Optional[aioredis.Redis] = None
        self._background_tasks: Set[asyncio.Task] = set()
        
    async def initialize(self):
        """Initialize the collaboration protocol."""
        # Connect to Redis for distributed coordination
        if self.redis_url:
            self.redis_client = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        
        # Start background tasks
        self._start_background_tasks()
        
        logger.info("Collaboration protocol initialized")
    
    async def shutdown(self):
        """Shutdown the collaboration protocol."""
        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
        
        # Wait for tasks to complete
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        
        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()
        
        logger.info("Collaboration protocol shutdown")
    
    def _start_background_tasks(self):
        """Start background maintenance tasks."""
        # Ping connections periodically
        task = asyncio.create_task(self._ping_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        
        # Process operation queues
        task = asyncio.create_task(self._process_queues_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        
        # Clean up old sessions
        task = asyncio.create_task(self._cleanup_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
    
    async def _ping_loop(self):
        """Periodically ping WebSocket connections."""
        while True:
            try:
                await asyncio.sleep(30)  # Ping every 30 seconds
                await self.websocket_manager.ping_connections()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in ping loop: {e}")
    
    async def _process_queues_loop(self):
        """Process operation queues continuously."""
        while True:
            try:
                await asyncio.sleep(0.1)  # Process every 100ms
                await self._process_all_queues()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in queue processing loop: {e}")
    
    async def _cleanup_loop(self):
        """Clean up old sessions periodically."""
        while True:
            try:
                await asyncio.sleep(300)  # Clean up every 5 minutes
                await self._cleanup_old_sessions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
    
    async def _process_all_queues(self):
        """Process all operation queues."""
        for document_id, queue in list(self.operation_queues.items()):
            if queue.get_pending_count() > 0:
                await self._process_queue(document_id)
    
    async def _process_queue(self, document_id: str):
        """Process operations for a specific document."""
        queue = self.operation_queues.get(document_id)
        if not queue:
            return
        
        session = self.sessions.get(document_id)
        if not session:
            return
        
        # Process up to 10 operations at a time
        for _ in range(min(10, queue.get_pending_count())):
            operation = queue.dequeue()
            if operation:
                try:
                    await self._apply_operation(session, operation)
                    queue.mark_processed(operation.id)
                except Exception as e:
                    logger.error(f"Error processing operation {operation.id}: {e}")
                    # Re-queue on error
                    queue.enqueue(operation)
    
    async def _cleanup_old_sessions(self):
        """Clean up sessions with no participants."""
        for doc_id in list(self.sessions.keys()):
            session = self.sessions[doc_id]
            if session.is_empty():
                # Check if session has been empty for more than 5 minutes
                if datetime.now(UTC) - session.created_at > timedelta(minutes=5):
                    await self.close_session(doc_id)
    
    async def create_session(self, document_id: str) -> CollaborationSession:
        """Create a new collaboration session."""
        if document_id in self.sessions:
            return self.sessions[document_id]
        
        session = CollaborationSession(document_id=document_id)
        self.sessions[document_id] = session
        self.operation_queues[document_id] = OperationQueue()
        
        # Store in Redis for distributed coordination
        if self.redis_client:
            await self.redis_client.set(
                f"collab:session:{document_id}",
                json.dumps({
                    "session_id": session.session_id,
                    "created_at": session.created_at.isoformat(),
                    "version": session.operation_version
                }),
                ex=3600  # Expire after 1 hour
            )
        
        logger.info(f"Created collaboration session for document {document_id}")
        return session
    
    async def close_session(self, document_id: str):
        """Close a collaboration session."""
        if document_id in self.sessions:
            del self.sessions[document_id]
        if document_id in self.operation_queues:
            del self.operation_queues[document_id]
        
        # Remove from Redis
        if self.redis_client:
            await self.redis_client.delete(f"collab:session:{document_id}")
        
        logger.info(f"Closed collaboration session for document {document_id}")
    
    async def join_session(
        self,
        websocket: WebSocket,
        user_id: str,
        document_id: str
    ) -> str:
        """
        Join a collaboration session.
        
        Returns:
            Connection ID
        """
        # Create session if it doesn't exist
        session = await self.create_session(document_id)
        
        # Add user to session
        session.add_participant(user_id)
        
        # Connect WebSocket
        connection_id = await self.websocket_manager.connect(
            websocket, user_id, document_id, session.session_id
        )
        
        # Send initial state
        await self._send_initial_state(connection_id, session)
        
        # Broadcast user joined
        await self._broadcast_user_joined(document_id, user_id, connection_id)
        
        return connection_id
    
    async def leave_session(self, connection_id: str):
        """Leave a collaboration session."""
        if connection_id not in self.websocket_manager.connections:
            return
        
        connection = self.websocket_manager.connections[connection_id]
        document_id = connection.document_id
        user_id = connection.user_id
        
        # Remove from session
        if document_id in self.sessions:
            self.sessions[document_id].remove_participant(user_id)
        
        # Disconnect WebSocket
        await self.websocket_manager.disconnect(connection_id)
        
        # Broadcast user left
        await self._broadcast_user_left(document_id, user_id)
    
    async def handle_client_operation(
        self,
        connection_id: str,
        operation_data: Dict[str, Any]
    ):
        """Handle an operation from a client."""
        if connection_id not in self.websocket_manager.connections:
            return
        
        connection = self.websocket_manager.connections[connection_id]
        document_id = connection.document_id
        
        # Get session
        session = self.sessions.get(document_id)
        if not session:
            logger.error(f"No session for document {document_id}")
            return
        
        # Create operation
        operation = ModelOperation.from_dict(operation_data)
        operation.user_id = connection.user_id
        operation.session_id = connection.session_id
        operation.timestamp = datetime.now(UTC)
        operation.version = session.operation_version
        
        # Queue operation for processing
        queue = self.operation_queues.get(document_id)
        if queue:
            queue.enqueue(operation)
            
            # Send acknowledgment
            await self.websocket_manager.send_to_connection(
                connection_id,
                {
                    "type": "operation_ack",
                    "operation_id": operation.id,
                    "status": "queued"
                }
            )
    
    async def _apply_operation(
        self,
        session: CollaborationSession,
        operation: ModelOperation
    ):
        """Apply an operation to the document."""
        # Transform against pending operations
        transformed = await self._transform_against_pending(session, operation)
        
        if transformed.is_no_op():
            logger.debug(f"Operation {operation.id} became no-op after transformation")
            return
        
        # Apply to document (would integrate with FreeCAD here)
        success = await self._apply_to_document(session.document_id, transformed)
        
        if success:
            # Update version
            transformed.version = session.increment_version()
            
            # Add to history
            session.operation_history.append(transformed)
            
            # Broadcast to other clients
            await self._broadcast_operation(
                session.document_id,
                transformed,
                exclude={operation.session_id}
            )
            
            # Store in Redis for persistence
            if self.redis_client:
                await self._store_operation(session.document_id, transformed)
        else:
            # Handle failure
            logger.error(f"Failed to apply operation {operation.id}")
            await self._handle_operation_failure(session, operation)
    
    async def _transform_against_pending(
        self,
        session: CollaborationSession,
        operation: ModelOperation
    ) -> ModelOperation:
        """Transform operation against pending operations."""
        current_op = operation
        
        # Transform against operations in history since this operation's version
        for historical_op in session.operation_history:
            if historical_op.version > operation.version:
                result = self.operation_transform.transform_operation(
                    current_op,
                    historical_op,
                    ConflictResolutionStrategy.MERGE
                )
                current_op = result.op1_prime
                
                if not result.conflict_resolved:
                    # Add to conflict queue
                    session.conflict_queue.append({
                        "operation": current_op.to_dict(),
                        "conflict_with": historical_op.to_dict(),
                        "metadata": result.resolution_metadata
                    })
        
        return current_op
    
    async def _apply_to_document(
        self,
        document_id: str,
        operation: ModelOperation
    ) -> bool:
        """
        Apply operation to the actual FreeCAD document.
        
        This would integrate with FreeCADDocumentManager.
        """
        # TODO: Integrate with FreeCADDocumentManager
        # For now, just return success
        return True
    
    async def _handle_operation_failure(
        self,
        session: CollaborationSession,
        operation: ModelOperation
    ):
        """Handle a failed operation."""
        # Notify the user who sent the operation
        await self.websocket_manager.send_to_user(
            operation.user_id,
            {
                "type": "operation_failed",
                "operation_id": operation.id,
                "error": "Failed to apply operation"
            }
        )
    
    async def _send_initial_state(
        self,
        connection_id: str,
        session: CollaborationSession
    ):
        """Send initial document state to a new connection."""
        # Get current document state
        # TODO: Get from FreeCADDocumentManager
        
        await self.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "initial_state",
                "document_id": session.document_id,
                "version": session.operation_version,
                "participants": list(session.participants),
                "pending_conflicts": len(session.conflict_queue)
            }
        )
    
    async def _broadcast_operation(
        self,
        document_id: str,
        operation: ModelOperation,
        exclude: Optional[Set[str]] = None
    ):
        """Broadcast operation to all clients."""
        message = {
            "type": "operation",
            "operation": operation.to_dict()
        }
        
        await self.websocket_manager.broadcast_to_document(
            document_id, message, exclude
        )
    
    async def _broadcast_user_joined(
        self,
        document_id: str,
        user_id: str,
        connection_id: str
    ):
        """Broadcast that a user joined."""
        message = {
            "type": "user_joined",
            "user_id": user_id,
            "timestamp": datetime.now(UTC).isoformat()
        }
        
        await self.websocket_manager.broadcast_to_document(
            document_id, message, exclude={connection_id}
        )
    
    async def _broadcast_user_left(self, document_id: str, user_id: str):
        """Broadcast that a user left."""
        message = {
            "type": "user_left",
            "user_id": user_id,
            "timestamp": datetime.now(UTC).isoformat()
        }
        
        await self.websocket_manager.broadcast_to_document(document_id, message)
    
    async def _store_operation(self, document_id: str, operation: ModelOperation):
        """Store operation in Redis for persistence."""
        if not self.redis_client:
            return
        
        key = f"collab:ops:{document_id}"
        await self.redis_client.rpush(
            key,
            json.dumps(operation.to_dict())
        )
        
        # Keep only last 1000 operations
        await self.redis_client.ltrim(key, -1000, -1)
        
        # Set expiration
        await self.redis_client.expire(key, 3600)  # 1 hour
    
    async def get_operation_history(
        self,
        document_id: str,
        limit: int = 100
    ) -> List[ModelOperation]:
        """Get operation history for a document."""
        if document_id in self.sessions:
            session = self.sessions[document_id]
            return list(session.operation_history)[-limit:]
        
        # Try to get from Redis
        if self.redis_client:
            key = f"collab:ops:{document_id}"
            ops_data = await self.redis_client.lrange(key, -limit, -1)
            return [
                ModelOperation.from_dict(json.loads(op_str))
                for op_str in ops_data
            ]
        
        return []
    
    async def resolve_conflict(
        self,
        document_id: str,
        conflict_id: str,
        resolution: Dict[str, Any]
    ):
        """Resolve a conflict manually."""
        session = self.sessions.get(document_id)
        if not session:
            return
        
        # Find and remove conflict from queue
        conflict = None
        for i, c in enumerate(session.conflict_queue):
            if c.get("id") == conflict_id:
                conflict = session.conflict_queue.pop(i)
                break
        
        if not conflict:
            return
        
        # Apply resolution
        resolved_op = ModelOperation.from_dict(resolution.get("operation"))
        
        # Queue for application
        queue = self.operation_queues.get(document_id)
        if queue:
            queue.enqueue(resolved_op)
        
        # Notify clients
        await self.websocket_manager.broadcast_to_document(
            document_id,
            {
                "type": "conflict_resolved",
                "conflict_id": conflict_id,
                "resolution": resolution
            }
        )