"""
WebSocket endpoints for real-time collaborative FreeCAD model editing.
Implements Task 7.21: Collaborative Editing and Real-time Synchronization.
"""

import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, UTC

from fastapi import (
    APIRouter,
    WebSocket,
    WebSocketDisconnect,
    Depends,
    HTTPException,
    status,
    Query
)
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user_ws
from app.middleware.jwt_middleware import get_current_user
from app.models.user import User
from app.services.collaboration_protocol import CollaborationProtocol
from app.services.presence_awareness import PresenceAwareness, Point3D, ViewportInfo
from app.services.collaborative_locking import CollaborativeLocking, LockRequest, LockType
from app.services.offline_sync import OfflineSync
from app.services.change_tracker import ChangeTracker, ModelChange
from app.services.operational_transform import ModelOperation
from app.core.config import settings
from app.utils.color_utils import generate_user_color

logger = logging.getLogger(__name__)

router = APIRouter()

# Turkish localization messages
COLLABORATION_MESSAGES_TR = {
    'user_joined': '{user} düzenlemeye katıldı',
    'user_left': '{user} düzenlemeden ayrıldı',
    'object_locked': 'Nesne {user} tarafından düzenleniyor',
    'conflict_detected': 'Çakışma tespit edildi',
    'changes_synced': 'Değişiklikler senkronize edildi',
    'offline_mode': 'Çevrimdışı modda çalışıyorsunuz',
    'reconnected': 'Bağlantı yeniden kuruldu',
    'lock_acquired': 'Kilit alındı',
    'lock_released': 'Kilit bırakıldı',
    'operation_applied': 'İşlem uygulandı',
    'operation_failed': 'İşlem başarısız',
    'sync_complete': 'Senkronizasyon tamamlandı',
    'sync_failed': 'Senkronizasyon başarısız',
    'connection_established': 'Bağlantı kuruldu',
    'connection_lost': 'Bağlantı koptu',
    'saving_changes': 'Değişiklikler kaydediliyor',
    'loading_document': 'Belge yükleniyor',
    'document_locked': 'Belge kilitli',
    'insufficient_permissions': 'Yetersiz yetki'
}

# Initialize services
collaboration_protocol = CollaborationProtocol()
presence_awareness = PresenceAwareness()
collaborative_locking = CollaborativeLocking()
offline_sync = OfflineSync()
change_tracker = ChangeTracker()


async def startup():
    """Initialize collaboration services on startup."""
    await collaboration_protocol.initialize()
    await presence_awareness.initialize()
    await collaborative_locking.initialize()
    logger.info("Collaboration services initialized")


async def shutdown():
    """Cleanup collaboration services on shutdown."""
    await collaboration_protocol.shutdown()
    await presence_awareness.shutdown()
    await collaborative_locking.shutdown()
    logger.info("Collaboration services shut down")


@router.websocket("/ws/collaborate/{document_id}")
async def collaborate(
    websocket: WebSocket,
    document_id: str,
    token: str = Query(None),
    db: Session = Depends(get_db)
):
    """
    Main WebSocket endpoint for collaborative editing.
    
    Handles:
    - Real-time operation synchronization
    - Presence awareness
    - Lock management
    - Offline sync
    """
    connection_id = None
    user = None
    
    try:
        # Authenticate user
        user = await get_current_user_ws(token, db)
        if not user:
            logger.warning(f"WebSocket authentication failed for document {document_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        
        logger.info(f"User {user.id} connecting to document {document_id}")
        
        # Join collaboration session
        connection_id = await collaboration_protocol.join_session(
            websocket, str(user.id), document_id
        )
        
        # Register for offline sync
        offline_sync.register_client(str(user.id), document_id)
        
        # Update presence
        await presence_awareness.update_user_presence(
            document_id,
            str(user.id),
            {
                "name": user.full_name or user.email,
                "status": "active",
                "color": generate_user_color(str(user.id), method="palette")
            }
        )
        
        # Send connection established message
        await websocket.send_json({
            "type": "connection_established",
            "message": COLLABORATION_MESSAGES_TR['connection_established'],
            "connection_id": connection_id,
            "user_id": str(user.id)
        })
        
        # Handle messages
        while True:
            try:
                # Receive message
                data = await websocket.receive_json()
                message_type = data.get("type")
                
                logger.debug(f"Received message type: {message_type} from user {user.id}")
                
                # Message handler mapping for cleaner routing
                message_handlers = {
                    "operation": handle_operation,
                    "cursor_update": handle_cursor_update,
                    "selection_update": handle_selection_update,
                    "lock_request": handle_lock_request,
                    "lock_release": handle_lock_release,
                    "sync_request": handle_sync_request,
                    "presence_update": handle_presence_update,
                    "undo": handle_undo,
                    "redo": handle_redo,
                    "resolve_conflict": handle_conflict_resolution,
                }
                
                # Special handling for ping
                if message_type == "ping":
                    await websocket.send_json({"type": "pong"})
                elif message_type in message_handlers:
                    # Route to appropriate handler
                    handler = message_handlers[message_type]
                    await handler(connection_id, document_id, user, data)
                else:
                    # Unknown message type
                    logger.warning(f"Unknown message type: {message_type}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Unknown message type: {message_type}"
                    })
                    
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON format"
                })
            except Exception as e:
                logger.error(f"Error handling message: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
                
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for user {user.id if user else 'unknown'}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Cleanup on disconnect
        if connection_id:
            await collaboration_protocol.leave_session(connection_id)
        
        if user and document_id:
            # Mark offline for sync
            offline_sync.mark_client_offline(str(user.id))
            
            # Remove presence
            await presence_awareness.remove_user(document_id, str(user.id))
            
            # Release all locks
            await collaborative_locking.release_all_user_locks(document_id, str(user.id))
            
            logger.info(f"Cleaned up resources for user {user.id}")


async def handle_operation(
    connection_id: str,
    document_id: str,
    user: User,
    data: Dict[str, Any]
):
    """Handle model operation from client."""
    try:
        operation_data = data.get("operation")
        if not operation_data:
            return
        
        # Create a copy to avoid modifying the original
        operation_data_with_user = operation_data.copy()
        operation_data_with_user["user_id"] = str(user.id)
        
        # Track change
        operation = ModelOperation.from_dict(operation_data_with_user)
        change = ModelChange(
            user_id=str(user.id),
            operation=operation,
            affected_objects=[operation.object_id] if operation.object_id else []
        )
        change_tracker.record_change(change)
        
        # Handle through collaboration protocol
        await collaboration_protocol.handle_client_operation(
            connection_id, operation_data_with_user
        )
        
        # Store for offline sync
        await offline_sync.store_operation(document_id, operation)
        
    except Exception as e:
        logger.error(f"Error handling operation: {e}")
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "operation_error",
                "message": COLLABORATION_MESSAGES_TR['operation_failed'],
                "error": str(e)
            }
        )


async def handle_cursor_update(
    connection_id: str,
    document_id: str,
    user: User,
    data: Dict[str, Any]
):
    """Handle cursor position update."""
    try:
        position_data = data.get("position")
        viewport_data = data.get("viewport")
        
        if not position_data:
            return
        
        # Parse position
        position = Point3D(
            x=position_data.get("x", 0),
            y=position_data.get("y", 0),
            z=position_data.get("z", 0)
        )
        
        # Parse viewport if provided
        viewport = None
        if viewport_data:
            viewport = ViewportInfo.from_dict(viewport_data)
        
        # Update presence
        await presence_awareness.track_user_cursor(
            document_id,
            str(user.id),
            position,
            viewport
        )
        
        # Broadcast to others
        await collaboration_protocol.websocket_manager.broadcast_to_document(
            document_id,
            {
                "type": "cursor_update",
                "user_id": str(user.id),
                "position": position.to_dict(),
                "viewport": viewport.to_dict() if viewport else None
            },
            exclude={connection_id}
        )
        
    except Exception as e:
        logger.error(f"Error handling cursor update: {e}")


async def handle_selection_update(
    connection_id: str,
    document_id: str,
    user: User,
    data: Dict[str, Any]
):
    """Handle object selection update."""
    try:
        selected_objects = data.get("selected_objects", [])
        
        # Update presence
        can_select = await presence_awareness.track_user_selection(
            document_id,
            str(user.id),
            selected_objects
        )
        
        # Send confirmation with actual selected objects
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "selection_confirmed",
                "selected_objects": list(can_select)
            }
        )
        
        # Broadcast to others
        await collaboration_protocol.websocket_manager.broadcast_to_document(
            document_id,
            {
                "type": "selection_update",
                "user_id": str(user.id),
                "selected_objects": list(can_select)
            },
            exclude={connection_id}
        )
        
    except Exception as e:
        logger.error(f"Error handling selection update: {e}")


async def handle_lock_request(
    connection_id: str,
    document_id: str,
    user: User,
    data: Dict[str, Any]
):
    """Handle lock acquisition request."""
    try:
        object_ids = data.get("object_ids", [])
        lock_type_str = data.get("lock_type", "exclusive")
        timeout = data.get("timeout", 300)
        wait_timeout = data.get("wait_timeout", 0)
        
        # Create lock request
        request = LockRequest(
            user_id=str(user.id),
            object_ids=object_ids,
            lock_type=LockType(lock_type_str),
            timeout_seconds=timeout,
            wait_timeout_seconds=wait_timeout
        )
        
        # Acquire locks
        result = await collaborative_locking.acquire_locks(document_id, request)
        
        # Send result to requester
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "lock_result",
                "acquired": result.acquired,
                "failed": result.failed,
                "pending": result.pending,
                "success": result.success,
                "message": COLLABORATION_MESSAGES_TR['lock_acquired'] if result.success else None
            }
        )
        
        # Broadcast lock changes
        if result.acquired:
            await collaboration_protocol.websocket_manager.broadcast_to_document(
                document_id,
                {
                    "type": "locks_acquired",
                    "user_id": str(user.id),
                    "object_ids": result.acquired,
                    "lock_type": lock_type_str
                },
                exclude={connection_id}
            )
        
    except Exception as e:
        logger.error(f"Error handling lock request: {e}")
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "lock_error",
                "error": str(e)
            }
        )


async def handle_lock_release(
    connection_id: str,
    document_id: str,
    user: User,
    data: Dict[str, Any]
):
    """Handle lock release request."""
    try:
        object_ids = data.get("object_ids", [])
        
        # Release locks
        released = await collaborative_locking.release_locks(
            document_id,
            str(user.id),
            object_ids
        )
        
        # Send confirmation
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "locks_released",
                "object_ids": released,
                "message": COLLABORATION_MESSAGES_TR['lock_released']
            }
        )
        
        # Broadcast to others
        if released:
            await collaboration_protocol.websocket_manager.broadcast_to_document(
                document_id,
                {
                    "type": "locks_released",
                    "user_id": str(user.id),
                    "object_ids": released
                },
                exclude={connection_id}
            )
        
    except Exception as e:
        logger.error(f"Error handling lock release: {e}")
        # Notify client of the error
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "lock_release_error",
                "message": "Failed to release locks. Please try again.",
                "error": "An error occurred while releasing the locks."
            }
        )


async def handle_sync_request(
    connection_id: str,
    document_id: str,
    user: User,
    data: Dict[str, Any]
):
    """Handle synchronization request."""
    try:
        offline_operations = data.get("offline_operations", [])
        client_checksum = data.get("checksum")
        
        # Convert to ModelOperation objects
        operations = [
            ModelOperation.from_dict(op_data)
            for op_data in offline_operations
        ]
        
        # Handle reconnection sync
        result = await offline_sync.handle_reconnection(
            str(user.id),
            operations,
            client_checksum
        )
        
        # Send sync result
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "sync_result",
                "success": result.success,
                "operations_applied": result.operations_applied,
                "operations_rejected": result.operations_rejected,
                "conflicts_resolved": result.conflicts_resolved,
                "new_version": result.new_version,
                "new_checksum": result.new_checksum,
                "message": COLLABORATION_MESSAGES_TR['sync_complete'] if result.success 
                          else COLLABORATION_MESSAGES_TR['sync_failed']
            }
        )
        
        # Send transformed operations
        if result.transformed_operations:
            for op in result.transformed_operations:
                await collaboration_protocol.websocket_manager.send_to_connection(
                    connection_id,
                    {
                        "type": "operation",
                        "operation": op.to_dict()
                    }
                )
        
    except Exception as e:
        logger.error(f"Error handling sync request: {e}")
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "sync_error",
                "error": str(e),
                "message": COLLABORATION_MESSAGES_TR['sync_failed']
            }
        )


async def handle_presence_update(
    connection_id: str,
    document_id: str,
    user: User,
    data: Dict[str, Any]
):
    """Handle presence status update."""
    try:
        presence_data = data.get("presence", {})
        
        # Update presence
        await presence_awareness.update_user_presence(
            document_id,
            str(user.id),
            presence_data
        )
        
        # Get all users in document
        users = presence_awareness.get_document_users(document_id)
        
        # Broadcast updated presence list
        await collaboration_protocol.websocket_manager.broadcast_to_document(
            document_id,
            {
                "type": "presence_update",
                "users": [
                    {
                        "user_id": presence.user_id,
                        "name": presence.name,
                        "color": presence.color,
                        "status": presence.status.value,
                        "cursor_position": presence.cursor_position.to_dict() if presence.cursor_position else None
                    }
                    for presence in users
                ]
            }
        )
        
    except Exception as e:
        logger.error(f"Error handling presence update: {e}")


async def handle_undo(
    connection_id: str,
    document_id: str,
    user: User,
    data: Dict[str, Any]
):
    """Handle undo request."""
    try:
        # Perform undo
        group = await change_tracker.undo(str(user.id))
        
        if group:
            # Send confirmation
            await collaboration_protocol.websocket_manager.send_to_connection(
                connection_id,
                {
                    "type": "undo_complete",
                    "changes_undone": len(group.changes)
                }
            )
            
            # Broadcast changes
            for change in group.changes:
                if change.operation:
                    await collaboration_protocol.websocket_manager.broadcast_to_document(
                        document_id,
                        {
                            "type": "operation",
                            "operation": change.operation.to_dict(),
                            "is_undo": True
                        }
                    )
        else:
            await collaboration_protocol.websocket_manager.send_to_connection(
                connection_id,
                {
                    "type": "undo_failed",
                    "message": "Nothing to undo"
                }
            )
            
    except Exception as e:
        logger.error(f"Error handling undo: {e}")
        # Notify client of the error
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "undo_error",
                "message": "Failed to perform undo operation. Please try again.",
                "error": "An error occurred while processing the undo request."
            }
        )


async def handle_redo(
    connection_id: str,
    document_id: str,
    user: User,
    data: Dict[str, Any]
):
    """Handle redo request."""
    try:
        # Perform redo
        group = await change_tracker.redo(str(user.id))
        
        if group:
            # Send confirmation
            await collaboration_protocol.websocket_manager.send_to_connection(
                connection_id,
                {
                    "type": "redo_complete",
                    "changes_redone": len(group.changes)
                }
            )
            
            # Broadcast changes
            for change in group.changes:
                if change.operation:
                    await collaboration_protocol.websocket_manager.broadcast_to_document(
                        document_id,
                        {
                            "type": "operation",
                            "operation": change.operation.to_dict(),
                            "is_redo": True
                        }
                    )
        else:
            await collaboration_protocol.websocket_manager.send_to_connection(
                connection_id,
                {
                    "type": "redo_failed",
                    "message": "Nothing to redo"
                }
            )
            
    except Exception as e:
        logger.error(f"Error handling redo: {e}")
        # Notify client of the error
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "redo_error",
                "message": "Failed to perform redo operation. Please try again.",
                "error": "An error occurred while processing the redo request."
            }
        )


async def handle_conflict_resolution(
    connection_id: str,
    document_id: str,
    user: User,
    data: Dict[str, Any]
):
    """Handle manual conflict resolution."""
    conflict_id = None  # Define at the beginning to ensure it's always available
    try:
        conflict_id = data.get("conflict_id")
        resolution = data.get("resolution")
        
        if not conflict_id or not resolution:
            return
        
        # Apply resolution
        await collaboration_protocol.resolve_conflict(
            document_id,
            conflict_id,
            resolution
        )
        
        # Send confirmation
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "conflict_resolved",
                "conflict_id": conflict_id,
                "message": "Conflict resolved successfully"
            }
        )
        
    except Exception as e:
        logger.error(f"Error handling conflict resolution: {e}")
        # Notify client of the error
        await collaboration_protocol.websocket_manager.send_to_connection(
            connection_id,
            {
                "type": "conflict_resolution_error",
                "message": "Failed to resolve conflict. Please try again.",
                "error": "An error occurred while resolving the conflict.",
                "conflict_id": conflict_id  # Now always defined
            }
        )


# Color generation is now handled by the shared utility module in app.utils.color_utils


# HTTP endpoints for collaboration status

@router.get("/collaboration/status/{document_id}")
async def get_collaboration_status(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get collaboration status for a document."""
    try:
        # Get active users
        users = presence_awareness.get_document_users(document_id)
        
        # Get lock status
        user_locks = collaborative_locking.get_user_locks(document_id, str(current_user.id))
        
        # Get sync status
        sync_status = await offline_sync.get_sync_status(str(current_user.id))
        
        return {
            "document_id": document_id,
            "active_users": len(users),
            "users": [
                {
                    "user_id": u.user_id,
                    "name": u.name,
                    "status": u.status.value
                }
                for u in users
            ],
            "my_locks": [lock.object_id for lock in user_locks],
            "sync_status": sync_status,
            "can_undo": change_tracker.can_undo(str(current_user.id)),
            "can_redo": change_tracker.can_redo(str(current_user.id))
        }
        
    except Exception as e:
        logger.error(f"Error getting collaboration status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/collaboration/history/{document_id}")
async def get_change_history(
    document_id: str,
    limit: int = Query(100, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get change history for a document."""
    try:
        # Get change history
        changes = change_tracker.get_change_history(
            limit=limit,
            user_id=str(current_user.id)
        )
        
        return {
            "document_id": document_id,
            "changes": [
                {
                    "id": change.id,
                    "user_id": change.user_id,
                    "timestamp": change.timestamp.isoformat(),
                    "operation_type": change.operation.type.value if change.operation else None,
                    "affected_objects": change.affected_objects
                }
                for change in changes
            ],
            "total": len(changes)
        }
        
    except Exception as e:
        logger.error(f"Error getting change history: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.get("/collaboration/statistics")
async def get_collaboration_statistics(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get overall collaboration statistics."""
    try:
        stats = {
            "locking": collaborative_locking.get_statistics(),
            "sync": offline_sync.get_statistics(),
            "changes": change_tracker.get_statistics(),
            "conflicts": collaboration_protocol.conflict_resolver.get_conflict_statistics()
        }
        
        return stats
        
    except Exception as e:
        logger.error(f"Error getting collaboration statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )