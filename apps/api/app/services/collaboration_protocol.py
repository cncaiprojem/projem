"""
Collaboration Protocol for Real-time FreeCAD Model Synchronization.
Manages WebSocket connections, operation queues, and conflict resolution.
"""

import asyncio
import json
import logging
import random
import time
from datetime import datetime, UTC, timedelta
from typing import Dict, List, Set, Optional, Any, Callable, Union
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
from app.core.settings import settings

logger = logging.getLogger(__name__)

# Configuration constants
OPERATION_HISTORY_MAX_LENGTH = 1000
OPERATION_QUEUE_MAX_SIZE = 10000
PROCESS_QUEUE_INTERVAL_MS = 100
CLEANUP_INTERVAL_SECONDS = 300
REDIS_OPERATION_EXPIRE_SECONDS = 3600
REDIS_OPERATION_TRIM_LIMIT = 1000

@dataclass
class CollaborationSession:
    """Represents a collaboration session for a FreeCAD document."""
    document_id: str
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    participants: Set[str] = field(default_factory=set)
    operation_version: int = 0
    operation_history: deque = field(default_factory=lambda: deque(maxlen=OPERATION_HISTORY_MAX_LENGTH))
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
    """Manages operation queuing and ordering with retry support."""
    
    def __init__(self, max_size: int = OPERATION_QUEUE_MAX_SIZE):
        self.queue: deque = deque(maxlen=max_size)
        self.processing: Dict[str, ModelOperation] = {}
        self.processed: Set[str] = set()
        self.retry_counts: Dict[str, int] = {}  # Track retry attempts
        self.dead_letter_queue: deque = deque()  # For operations that exceed max retries
        self.max_retries: int = 3
        self.retry_delays: Dict[str, float] = {}  # Track exponential backoff delays
        
    def enqueue(self, operation: ModelOperation, is_retry: bool = False) -> bool:
        """Add operation to queue with retry tracking."""
        if operation.id not in self.processed:
            if is_retry:
                # Check if max retries exceeded
                retry_count = self.retry_counts.get(operation.id, 0)
                if retry_count >= self.max_retries:
                    # Move to dead letter queue
                    self.dead_letter_queue.append(operation)
                    logger.warning(
                        f"Operation {operation.id} moved to DLQ after {retry_count} retries"
                    )
                    return False
                
                # Update retry count and calculate exponential backoff
                self.retry_counts[operation.id] = retry_count + 1
                # Exponential backoff: 2^retry_count seconds with jitter
                base_delay = 2 ** retry_count
                # Correctly calculate ±10% jitter: random value between -0.1 and +0.1
                jitter_factor = (random.random() - 0.5) * 0.2  # Random value in [-0.1, 0.1]
                jittered_delay = base_delay * (1 + jitter_factor)  # Apply ±10% jitter
                self.retry_delays[operation.id] = time.time() + jittered_delay
            else:
                # Initialize retry count for new operations
                self.retry_counts[operation.id] = 0
                self.retry_delays[operation.id] = 0
            
            self.queue.append(operation)
            return True
        return False
    
    def dequeue(self) -> Optional[ModelOperation]:
        """Get next operation from queue, respecting retry delays."""
        current_time = time.time()
        
        # Find first operation that's ready to process
        for i, operation in enumerate(self.queue):
            delay_end = self.retry_delays.get(operation.id, 0)
            if delay_end <= current_time:
                # Remove from queue and add to processing
                self.queue.rotate(-i)  # Rotate to position
                operation = self.queue.popleft()
                self.queue.rotate(i)  # Restore original order
                self.processing[operation.id] = operation
                return operation
        
        return None
    
    def mark_processed(self, operation_id: str):
        """Mark operation as processed."""
        if operation_id in self.processing:
            del self.processing[operation_id]
        self.processed.add(operation_id)
        # Clean up retry tracking
        self.retry_counts.pop(operation_id, None)
        self.retry_delays.pop(operation_id, None)
    
    def get_pending_count(self) -> int:
        """Get count of pending operations."""
        return len(self.queue)
    
    def get_processing_count(self) -> int:
        """Get count of processing operations."""
        return len(self.processing)
    
    def get_dlq_count(self) -> int:
        """Get count of dead letter queue operations."""
        return len(self.dead_letter_queue)
    
    def clear(self):
        """Clear all queues."""
        self.queue.clear()
        self.processing.clear()
        self.processed.clear()
        self.retry_counts.clear()
        self.retry_delays.clear()
        self.dead_letter_queue.clear()


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
                await asyncio.sleep(PROCESS_QUEUE_INTERVAL_MS / 1000)  # Process at configured interval
                await self._process_all_queues()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in queue processing loop: {e}")
    
    async def _cleanup_loop(self):
        """Clean up old sessions periodically."""
        while True:
            try:
                await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)  # Clean up at configured interval
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
                    # Re-queue with retry tracking
                    if not queue.enqueue(operation, is_retry=True):
                        # Operation moved to DLQ, notify relevant connections
                        await self._notify_operation_failure(session, operation, str(e))
    
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
                ex=REDIS_OPERATION_EXPIRE_SECONDS  # Expire at configured interval
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
        
        Integrates with FreeCADDocumentManager to apply operations.
        """
        import asyncio
        from app.services.freecad_document_manager import document_manager, DocumentException
        
        try:
            # Get document handle
            doc_handle = document_manager.get_document(document_id)
            if not doc_handle:
                logger.warning(f"Document {document_id} not found, attempting to create/open")
                # Try to open or create the document
                doc_handle = await asyncio.to_thread(
                    document_manager.open_or_create_document,
                    document_id
                )
                if not doc_handle:
                    logger.error(f"Failed to open/create document {document_id}")
                    return False
            
            # Apply operation based on type
            doc = doc_handle.document
            success = False
            
            if operation.type == OperationType.CREATE:
                # Create new object
                object_id = operation.parameters.get("new_object_id", str(uuid.uuid4()))
                object_type = operation.parameters.get("type", "Part::Feature")
                object_data = operation.parameters.get("object_data", {})
                
                success = await asyncio.to_thread(
                    self._create_freecad_object,
                    doc,
                    object_id,
                    object_type,
                    object_data
                )
                
            elif operation.type == OperationType.DELETE:
                # Delete object
                success = await asyncio.to_thread(
                    self._delete_freecad_object,
                    doc,
                    operation.object_id
                )
                
            elif operation.type == OperationType.MODIFY:
                # Modify object properties
                success = await asyncio.to_thread(
                    self._modify_freecad_object,
                    doc,
                    operation.object_id,
                    operation.parameters
                )
                
            elif operation.type == OperationType.MOVE:
                # Move object
                position = operation.parameters.get("position", {})
                rotation = operation.parameters.get("rotation")
                
                success = await asyncio.to_thread(
                    self._move_freecad_object,
                    doc,
                    operation.object_id,
                    position,
                    rotation
                )
                
            elif operation.type == OperationType.ROTATE:
                # Rotate object
                rotation = operation.parameters.get("rotation", {})
                success = await asyncio.to_thread(
                    self._rotate_freecad_object,
                    doc,
                    operation.object_id,
                    rotation
                )
                
            elif operation.type == OperationType.SCALE:
                # Scale object
                scale = operation.parameters.get("scale", 1.0)
                success = await asyncio.to_thread(
                    self._scale_freecad_object,
                    doc,
                    operation.object_id,
                    scale
                )
            
            # Recompute document if operation succeeded
            if success and hasattr(doc, "recompute"):
                await asyncio.to_thread(doc.recompute)
            
            # Auto-save if configured
            if success and hasattr(doc_handle, "auto_save") and doc_handle.auto_save:
                await asyncio.to_thread(doc_handle.save)
            
            return success
            
        except DocumentException as e:
            logger.error(f"Document error applying operation {operation.id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error applying operation {operation.id}: {e}")
            return False
    
    def _create_freecad_object(
        self,
        doc,
        object_id: str,
        object_type: str,
        object_data: Dict[str, Any]
    ) -> bool:
        """Create a FreeCAD object (blocking operation)."""
        try:
            if hasattr(doc, "addObject"):
                obj = doc.addObject(object_type, object_id)
                
                # Apply initial properties
                for prop_name, prop_value in object_data.items():
                    if prop_name not in ["type", "id"] and hasattr(obj, prop_name):
                        try:
                            setattr(obj, prop_name, prop_value)
                        except Exception as e:
                            logger.warning(f"Could not set property {prop_name}: {e}")
                
                return True
        except Exception as e:
            logger.error(f"Failed to create object {object_id}: {e}")
        return False
    
    def _delete_freecad_object(self, doc, object_id: str) -> bool:
        """Delete a FreeCAD object (blocking operation)."""
        try:
            if hasattr(doc, "getObject") and hasattr(doc, "removeObject"):
                obj = doc.getObject(object_id)
                if obj:
                    doc.removeObject(object_id)
                    return True
                logger.warning(f"Object {object_id} not found for deletion")
        except Exception as e:
            logger.error(f"Failed to delete object {object_id}: {e}")
        return False
    
    def _modify_freecad_object(
        self,
        doc,
        object_id: str,
        parameters: Dict[str, Any]
    ) -> bool:
        """Modify a FreeCAD object (blocking operation)."""
        try:
            if hasattr(doc, "getObject"):
                obj = doc.getObject(object_id)
                if obj:
                    for prop_name, prop_value in parameters.items():
                        if hasattr(obj, prop_name):
                            try:
                                setattr(obj, prop_name, prop_value)
                            except Exception as e:
                                logger.warning(f"Could not modify property {prop_name}: {e}")
                    return True
                logger.warning(f"Object {object_id} not found for modification")
        except Exception as e:
            logger.error(f"Failed to modify object {object_id}: {e}")
        return False
    
    def _move_freecad_object(
        self,
        doc,
        object_id: str,
        position: Dict[str, Any],
        rotation: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Move a FreeCAD object (blocking operation)."""
        try:
            if hasattr(doc, "getObject"):
                obj = doc.getObject(object_id)
                if obj and hasattr(obj, "Placement"):
                    import FreeCAD
                    
                    placement = obj.Placement
                    
                    # Update position
                    if position and any(k in position for k in ["x", "y", "z"]):
                        placement.Base = FreeCAD.Vector(
                            position.get("x", placement.Base.x),
                            position.get("y", placement.Base.y),
                            position.get("z", placement.Base.z)
                        )
                    
                    # Update rotation if provided
                    if rotation:
                        if "angle" in rotation and "axis" in rotation:
                            axis = rotation["axis"]
                            placement.Rotation = FreeCAD.Rotation(
                                FreeCAD.Vector(
                                    axis.get("x", 0),
                                    axis.get("y", 0),
                                    axis.get("z", 1)
                                ),
                                rotation["angle"]
                            )
                    
                    obj.Placement = placement
                    return True
                logger.warning(f"Object {object_id} not found for moving")
        except Exception as e:
            logger.error(f"Failed to move object {object_id}: {e}")
        return False
    
    def _rotate_freecad_object(
        self,
        doc,
        object_id: str,
        rotation: Dict[str, Any]
    ) -> bool:
        """Rotate a FreeCAD object (blocking operation)."""
        try:
            if hasattr(doc, "getObject"):
                obj = doc.getObject(object_id)
                if obj and hasattr(obj, "Placement"):
                    import FreeCAD
                    
                    placement = obj.Placement
                    
                    if "angle" in rotation and "axis" in rotation:
                        axis = rotation["axis"]
                        # Apply rotation relative to current rotation
                        new_rotation = FreeCAD.Rotation(
                            FreeCAD.Vector(
                                axis.get("x", 0),
                                axis.get("y", 0),
                                axis.get("z", 1)
                            ),
                            rotation["angle"]
                        )
                        placement.Rotation = placement.Rotation * new_rotation
                        obj.Placement = placement
                        return True
                logger.warning(f"Object {object_id} not found for rotation")
        except Exception as e:
            logger.error(f"Failed to rotate object {object_id}: {e}")
        return False
    
    def _scale_freecad_object(
        self,
        doc,
        object_id: str,
        scale: Union[float, Dict[str, float]]
    ) -> bool:
        """Scale a FreeCAD object (blocking operation)."""
        try:
            if hasattr(doc, "getObject"):
                obj = doc.getObject(object_id)
                if obj:
                    import FreeCAD
                    
                    # Determine scale factors
                    if isinstance(scale, (int, float)):
                        scale_x = scale_y = scale_z = scale
                    else:
                        scale_x = scale.get("x", 1.0)
                        scale_y = scale.get("y", 1.0)
                        scale_z = scale.get("z", 1.0)
                    
                    # Apply scaling
                    if hasattr(obj, "Shape"):
                        # Create scaling matrix
                        mat = FreeCAD.Matrix()
                        mat.scale(scale_x, scale_y, scale_z)
                        
                        # Apply to shape
                        obj.Shape = obj.Shape.transformGeometry(mat)
                        return True
                    elif hasattr(obj, "Scale"):
                        # Some objects have direct scale property
                        obj.Scale = FreeCAD.Vector(scale_x, scale_y, scale_z)
                        return True
                    
                logger.warning(f"Object {object_id} not found or cannot be scaled")
        except Exception as e:
            logger.error(f"Failed to scale object {object_id}: {e}")
        return False
    
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
    
    async def _notify_operation_failure(
        self,
        session: CollaborationSession,
        operation: ModelOperation,
        error_message: str
    ):
        """Notify about operation failure that exceeded retry limit."""
        # Notify all participants about the permanent failure
        await self.websocket_manager.send_to_document(
            session.document_id,
            {
                "type": "operation_dlq",
                "operation_id": operation.id,
                "user_id": operation.user_id,
                "error": error_message,
                "message": "Operation moved to dead letter queue after max retries"
            }
        )
    
    async def _send_initial_state(
        self,
        connection_id: str,
        session: CollaborationSession
    ):
        """Send initial document state to a new connection."""
        import asyncio
        from app.services.freecad_document_manager import document_manager
        
        # Get current document state from FreeCADDocumentManager
        document_state = {}
        document_objects = []
        
        try:
            # Check if document exists in document manager
            if session.document_id in document_manager._doc_handles:
                # Get the real FreeCAD document handle
                doc_handle = document_manager._doc_handles[session.document_id]
                
                # Get comprehensive snapshot using adapter
                snapshot = await asyncio.to_thread(
                    document_manager.adapter.take_snapshot,
                    doc_handle
                )
                
                # Extract document objects and properties
                if snapshot:
                    document_objects = snapshot.get("objects", [])
                    document_state = {
                        "properties": snapshot.get("properties", {}),
                        "metadata": snapshot.get("metadata", {}),
                        "object_count": len(document_objects)
                    }
                    
                    logger.info(
                        "Retrieved document state from FreeCADDocumentManager",
                        document_id=session.document_id,
                        object_count=len(document_objects)
                    )
            else:
                # Try to open or create the document if not in handles
                logger.info(
                    "Document not in handles, attempting to open",
                    document_id=session.document_id
                )
                
                # Extract job_id from document_id (format: doc_{job_id})
                job_id = session.document_id.replace("doc_", "") if session.document_id.startswith("doc_") else session.document_id
                
                try:
                    # Try to open the document
                    metadata = await asyncio.to_thread(
                        document_manager.open_document,
                        job_id=job_id,
                        create_if_not_exists=True
                    )
                    
                    # Now try to get the handle again
                    if session.document_id in document_manager._doc_handles:
                        doc_handle = document_manager._doc_handles[session.document_id]
                        snapshot = await asyncio.to_thread(
                            document_manager.adapter.take_snapshot,
                            doc_handle
                        )
                        
                        if snapshot:
                            document_objects = snapshot.get("objects", [])
                            document_state = {
                                "properties": snapshot.get("properties", {}),
                                "metadata": snapshot.get("metadata", {}),
                                "object_count": len(document_objects)
                            }
                except Exception as e:
                    logger.warning(
                        "Could not open document from manager",
                        document_id=session.document_id,
                        error=str(e)
                    )
            
            # Get operation history for the document
            operation_history = []
            if session.operation_history:
                # Send last 100 operations for context
                operation_history = [
                    op.to_dict() if hasattr(op, 'to_dict') else op
                    for op in list(session.operation_history)[-100:]
                ]
            
        except Exception as e:
            logger.error(
                "Error retrieving document state",
                document_id=session.document_id,
                error=str(e),
                exc_info=True
            )
            # Continue with empty state if error occurs
        
        # Prepare the complete initial state message
        initial_state_message = {
            "type": "initial_state",
            "document_id": session.document_id,
            "version": session.operation_version,
            "participants": list(session.participants),
            "pending_conflicts": len(session.conflict_queue),
            "document_state": document_state,
            "objects": document_objects,
            "operation_history": operation_history,
            "timestamp": datetime.now(UTC).isoformat()
        }
        
        # Send the complete initial state to the new connection
        await self.websocket_manager.send_to_connection(
            connection_id,
            initial_state_message
        )
        
        logger.info(
            "Sent initial state to connection",
            connection_id=connection_id,
            document_id=session.document_id,
            object_count=len(document_objects),
            history_count=len(operation_history),
            participant_count=len(session.participants)
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
        
        # Keep only last configured number of operations
        await self.redis_client.ltrim(key, -REDIS_OPERATION_TRIM_LIMIT, -1)
        
        # Set expiration
        await self.redis_client.expire(key, REDIS_OPERATION_EXPIRE_SECONDS)  # Configured expiry
    
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