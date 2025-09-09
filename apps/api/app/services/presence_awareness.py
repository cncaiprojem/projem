"""
Presence Awareness System for Collaborative FreeCAD Editing.
Tracks active users, cursor positions, selections, and object locks.
"""

import asyncio
import logging
from datetime import datetime, UTC, timedelta
from typing import Dict, List, Set, Optional, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum
import uuid
import json
from collections import defaultdict

from redis import asyncio as aioredis

from app.core.config import settings

logger = logging.getLogger(__name__)


class UserStatus(str, Enum):
    """User status in collaboration."""
    ACTIVE = "active"
    IDLE = "idle"
    AWAY = "away"
    OFFLINE = "offline"


class LockType(str, Enum):
    """Types of object locks."""
    EXCLUSIVE = "exclusive"  # Only one user can edit
    SHARED = "shared"  # Multiple users can view/read
    PENDING = "pending"  # Lock request pending


@dataclass
class Point3D:
    """3D point in space."""
    x: float
    y: float
    z: float
    
    def to_dict(self) -> Dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}
    
    @classmethod
    def from_dict(cls, data: Dict[str, float]) -> "Point3D":
        return cls(x=data["x"], y=data["y"], z=data["z"])
    
    def distance_to(self, other: "Point3D") -> float:
        """Calculate Euclidean distance to another point."""
        return ((self.x - other.x) ** 2 + 
                (self.y - other.y) ** 2 + 
                (self.z - other.z) ** 2) ** 0.5


@dataclass
class ViewportInfo:
    """User's viewport information."""
    camera_position: Point3D
    camera_target: Point3D
    camera_up: Tuple[float, float, float] = (0, 0, 1)
    zoom_level: float = 1.0
    viewport_size: Tuple[int, int] = (1920, 1080)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "camera_position": self.camera_position.to_dict(),
            "camera_target": self.camera_target.to_dict(),
            "camera_up": self.camera_up,
            "zoom_level": self.zoom_level,
            "viewport_size": self.viewport_size
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ViewportInfo":
        return cls(
            camera_position=Point3D.from_dict(data["camera_position"]),
            camera_target=Point3D.from_dict(data["camera_target"]),
            camera_up=tuple(data.get("camera_up", [0, 0, 1])),
            zoom_level=data.get("zoom_level", 1.0),
            viewport_size=tuple(data.get("viewport_size", [1920, 1080]))
        )


@dataclass
class UserPresence:
    """Complete user presence information."""
    user_id: str
    name: str
    color: str  # Hex color for UI representation
    avatar_url: Optional[str] = None
    status: UserStatus = UserStatus.ACTIVE
    cursor_position: Optional[Point3D] = None
    viewport: Optional[ViewportInfo] = None
    selected_objects: Set[str] = field(default_factory=set)
    locked_objects: Set[str] = field(default_factory=set)
    last_activity: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "color": self.color,
            "avatar_url": self.avatar_url,
            "status": self.status.value,
            "cursor_position": self.cursor_position.to_dict() if self.cursor_position else None,
            "viewport": self.viewport.to_dict() if self.viewport else None,
            "selected_objects": list(self.selected_objects),
            "locked_objects": list(self.locked_objects),
            "last_activity": self.last_activity.isoformat(),
            "metadata": self.metadata
        }
    
    def update_activity(self):
        """Update last activity timestamp."""
        self.last_activity = datetime.now(UTC)
        if self.status == UserStatus.IDLE:
            self.status = UserStatus.ACTIVE
    
    def check_idle(self, idle_threshold_seconds: int = 60) -> bool:
        """Check if user should be marked as idle."""
        if datetime.now(UTC) - self.last_activity > timedelta(seconds=idle_threshold_seconds):
            if self.status == UserStatus.ACTIVE:
                self.status = UserStatus.IDLE
                return True
        return False


@dataclass
class ObjectLock:
    """Lock information for an object."""
    object_id: str
    user_id: str
    lock_type: LockType
    acquired_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if lock has expired."""
        if self.expires_at:
            return datetime.now(UTC) > self.expires_at
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "object_id": self.object_id,
            "user_id": self.user_id,
            "lock_type": self.lock_type.value,
            "acquired_at": self.acquired_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "metadata": self.metadata
        }


class PresenceAwareness:
    """
    Manages user presence, cursor tracking, and object locking.
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        self.active_users: Dict[str, Dict[str, UserPresence]] = defaultdict(dict)  # document_id -> user_id -> presence
        self.user_cursors: Dict[str, Dict[str, Tuple[Point3D, datetime]]] = defaultdict(dict)
        self.user_selections: Dict[str, Dict[str, Set[str]]] = defaultdict(dict)
        self.object_locks: Dict[str, Dict[str, ObjectLock]] = defaultdict(dict)  # document_id -> object_id -> lock
        self.lock_queue: Dict[str, List[Tuple[str, str, LockType]]] = defaultdict(list)  # Pending lock requests
        
        self.redis_url = redis_url or settings.REDIS_URL
        self.redis_client: Optional[aioredis.Redis] = None
        
        # Throttling for cursor updates
        self.cursor_update_throttle: Dict[str, datetime] = {}
        self.cursor_throttle_ms = 33  # ~30 FPS
        
        self._background_tasks: Set[asyncio.Task] = set()
    
    async def initialize(self):
        """Initialize the presence awareness system."""
        # Connect to Redis for distributed state
        if self.redis_url:
            self.redis_client = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        
        # Start background tasks
        self._start_background_tasks()
        
        logger.info("Presence awareness system initialized")
    
    async def shutdown(self):
        """Shutdown the presence awareness system."""
        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
        
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        
        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()
        
        logger.info("Presence awareness system shutdown")
    
    def _start_background_tasks(self):
        """Start background maintenance tasks."""
        # Check for idle users
        task = asyncio.create_task(self._idle_check_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        
        # Clean up expired locks
        task = asyncio.create_task(self._lock_cleanup_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        
        # Sync with Redis
        task = asyncio.create_task(self._redis_sync_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
    
    async def _idle_check_loop(self):
        """Periodically check for idle users."""
        while True:
            try:
                await asyncio.sleep(10)  # Check every 10 seconds
                await self._check_idle_users()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in idle check loop: {e}")
    
    async def _lock_cleanup_loop(self):
        """Clean up expired locks."""
        while True:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds
                await self._cleanup_expired_locks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in lock cleanup loop: {e}")
    
    async def _redis_sync_loop(self):
        """Sync presence data with Redis."""
        while True:
            try:
                await asyncio.sleep(2)  # Sync every 2 seconds
                await self._sync_with_redis()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in Redis sync loop: {e}")
    
    async def _check_idle_users(self):
        """Check and update idle user status."""
        for doc_id, users in self.active_users.items():
            idle_users = []
            for user_id, presence in users.items():
                if presence.check_idle():
                    idle_users.append(user_id)
            
            # Broadcast idle status changes
            if idle_users:
                await self._broadcast_status_changes(doc_id, idle_users, UserStatus.IDLE)
    
    async def _cleanup_expired_locks(self):
        """Clean up expired object locks."""
        for doc_id, locks in list(self.object_locks.items()):
            expired = []
            for obj_id, lock in list(locks.items()):
                if lock.is_expired():
                    expired.append(obj_id)
                    del locks[obj_id]
            
            # Process lock queue for expired locks
            if expired:
                await self._process_lock_queue(doc_id, expired)
    
    async def _sync_with_redis(self):
        """Sync presence data with Redis for distributed coordination."""
        if not self.redis_client:
            return
        
        for doc_id, users in self.active_users.items():
            # Store presence data
            presence_key = f"presence:{doc_id}"
            presence_data = {
                user_id: json.dumps(presence.to_dict())
                for user_id, presence in users.items()
            }
            
            if presence_data:
                await self.redis_client.hset(presence_key, mapping=presence_data)
                await self.redis_client.expire(presence_key, 60)  # Expire after 1 minute
            
            # Store locks
            locks_key = f"locks:{doc_id}"
            locks_data = {
                obj_id: json.dumps(lock.to_dict())
                for obj_id, lock in self.object_locks[doc_id].items()
            }
            
            if locks_data:
                await self.redis_client.hset(locks_key, mapping=locks_data)
                await self.redis_client.expire(locks_key, 300)  # Expire after 5 minutes
    
    async def update_user_presence(
        self,
        document_id: str,
        user_id: str,
        presence_data: Dict[str, Any]
    ) -> UserPresence:
        """Update user presence information."""
        # Get or create presence
        if user_id not in self.active_users[document_id]:
            presence = UserPresence(
                user_id=user_id,
                name=presence_data.get("name", f"User {user_id[:8]}"),
                color=presence_data.get("color", self._generate_user_color(user_id))
            )
            self.active_users[document_id][user_id] = presence
        else:
            presence = self.active_users[document_id][user_id]
        
        # Update fields
        if "avatar_url" in presence_data:
            presence.avatar_url = presence_data["avatar_url"]
        if "status" in presence_data:
            presence.status = UserStatus(presence_data["status"])
        if "metadata" in presence_data:
            presence.metadata.update(presence_data["metadata"])
        
        presence.update_activity()
        
        # Store in Redis
        if self.redis_client:
            await self.redis_client.hset(
                f"presence:{document_id}",
                user_id,
                json.dumps(presence.to_dict())
            )
        
        logger.debug(f"Updated presence for user {user_id} in document {document_id}")
        
        return presence
    
    async def track_user_cursor(
        self,
        document_id: str,
        user_id: str,
        cursor_position: Point3D,
        viewport: Optional[ViewportInfo] = None
    ) -> bool:
        """
        Track 3D cursor position for awareness.
        
        Returns:
            True if update was broadcast, False if throttled
        """
        # Check throttling
        throttle_key = f"{document_id}:{user_id}"
        now = datetime.now(UTC)
        
        if throttle_key in self.cursor_update_throttle:
            last_update = self.cursor_update_throttle[throttle_key]
            if (now - last_update).total_seconds() * 1000 < self.cursor_throttle_ms:
                # Store update but don't broadcast yet
                self.user_cursors[document_id][user_id] = (cursor_position, now)
                return False
        
        # Update cursor position
        self.user_cursors[document_id][user_id] = (cursor_position, now)
        self.cursor_update_throttle[throttle_key] = now
        
        # Update presence
        if user_id in self.active_users[document_id]:
            presence = self.active_users[document_id][user_id]
            presence.cursor_position = cursor_position
            if viewport:
                presence.viewport = viewport
            presence.update_activity()
        
        # Broadcast update
        await self._broadcast_cursor_update(document_id, user_id, cursor_position, viewport)
        
        return True
    
    async def track_user_selection(
        self,
        document_id: str,
        user_id: str,
        selected_objects: List[str]
    ) -> Set[str]:
        """
        Track what objects user has selected.
        
        Returns:
            Set of objects that were successfully selected
        """
        selected_set = set(selected_objects)
        
        # Check for locked objects
        locked_by_others = set()
        for obj_id in selected_objects:
            lock = self.object_locks[document_id].get(obj_id)
            if lock and lock.user_id != user_id and lock.lock_type == LockType.EXCLUSIVE:
                locked_by_others.add(obj_id)
        
        # Only select objects not locked by others
        can_select = selected_set - locked_by_others
        
        # Update selection
        self.user_selections[document_id][user_id] = can_select
        
        # Update presence
        if user_id in self.active_users[document_id]:
            presence = self.active_users[document_id][user_id]
            presence.selected_objects = can_select
            presence.update_activity()
        
        # Try to acquire locks for selected objects
        for obj_id in can_select:
            await self.acquire_object_lock(
                document_id, user_id, obj_id, LockType.SHARED
            )
        
        # Broadcast selection update
        await self._broadcast_selection_update(document_id, user_id, list(can_select))
        
        return can_select
    
    async def acquire_object_lock(
        self,
        document_id: str,
        user_id: str,
        object_id: str,
        lock_type: LockType = LockType.EXCLUSIVE,
        timeout_seconds: int = 300
    ) -> bool:
        """
        Acquire lock for editing an object.
        
        Returns:
            True if lock was acquired, False otherwise
        """
        current_lock = self.object_locks[document_id].get(object_id)
        
        # Check if object is already locked
        if current_lock:
            if current_lock.user_id == user_id:
                # User already has lock - upgrade if needed
                if current_lock.lock_type == LockType.SHARED and lock_type == LockType.EXCLUSIVE:
                    current_lock.lock_type = LockType.EXCLUSIVE
                    current_lock.acquired_at = datetime.now(UTC)
                    current_lock.expires_at = datetime.now(UTC) + timedelta(seconds=timeout_seconds)
                    await self._broadcast_lock_update(document_id, object_id, user_id, LockType.EXCLUSIVE)
                return True
            elif current_lock.lock_type == LockType.EXCLUSIVE:
                # Object exclusively locked by another user
                # Add to queue
                self.lock_queue[document_id].append((user_id, object_id, lock_type))
                return False
            elif lock_type == LockType.SHARED:
                # Both want shared lock - compatible
                return True
            else:
                # Current is shared, requested is exclusive - queue it
                self.lock_queue[document_id].append((user_id, object_id, lock_type))
                return False
        
        # No current lock - acquire it
        lock = ObjectLock(
            object_id=object_id,
            user_id=user_id,
            lock_type=lock_type,
            expires_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds)
        )
        
        self.object_locks[document_id][object_id] = lock
        
        # Update user presence
        if user_id in self.active_users[document_id]:
            self.active_users[document_id][user_id].locked_objects.add(object_id)
        
        # Store in Redis
        if self.redis_client:
            await self.redis_client.hset(
                f"locks:{document_id}",
                object_id,
                json.dumps(lock.to_dict())
            )
        
        # Broadcast lock acquisition
        await self._broadcast_lock_update(document_id, object_id, user_id, lock_type)
        
        logger.info(f"User {user_id} acquired {lock_type} lock on {object_id}")
        
        return True
    
    async def release_object_lock(
        self,
        document_id: str,
        user_id: str,
        object_id: str
    ) -> bool:
        """
        Release lock on an object.
        
        Returns:
            True if lock was released, False if user didn't have lock
        """
        lock = self.object_locks[document_id].get(object_id)
        
        if not lock or lock.user_id != user_id:
            return False
        
        # Remove lock
        del self.object_locks[document_id][object_id]
        
        # Update user presence
        if user_id in self.active_users[document_id]:
            self.active_users[document_id][user_id].locked_objects.discard(object_id)
        
        # Remove from Redis
        if self.redis_client:
            await self.redis_client.hdel(f"locks:{document_id}", object_id)
        
        # Process lock queue
        await self._process_lock_queue(document_id, [object_id])
        
        # Broadcast lock release
        await self._broadcast_lock_release(document_id, object_id, user_id)
        
        logger.info(f"User {user_id} released lock on {object_id}")
        
        return True
    
    async def release_all_user_locks(self, document_id: str, user_id: str):
        """Release all locks held by a user."""
        user_locks = [
            obj_id for obj_id, lock in self.object_locks[document_id].items()
            if lock.user_id == user_id
        ]
        
        for obj_id in user_locks:
            await self.release_object_lock(document_id, user_id, obj_id)
    
    async def _process_lock_queue(self, document_id: str, released_objects: List[str]):
        """Process pending lock requests for released objects."""
        if document_id not in self.lock_queue:
            return
        
        queue = self.lock_queue[document_id]
        processed = []
        
        for i, (user_id, obj_id, lock_type) in enumerate(queue):
            if obj_id in released_objects:
                # Try to acquire lock
                if await self.acquire_object_lock(document_id, user_id, obj_id, lock_type):
                    processed.append(i)
        
        # Remove processed requests
        for i in reversed(processed):
            queue.pop(i)
    
    async def remove_user(self, document_id: str, user_id: str):
        """Remove user from document (user left)."""
        # Release all locks
        await self.release_all_user_locks(document_id, user_id)
        
        # Remove from tracking
        if user_id in self.active_users[document_id]:
            del self.active_users[document_id][user_id]
        
        if user_id in self.user_cursors[document_id]:
            del self.user_cursors[document_id][user_id]
        
        if user_id in self.user_selections[document_id]:
            del self.user_selections[document_id][user_id]
        
        # Remove from Redis
        if self.redis_client:
            await self.redis_client.hdel(f"presence:{document_id}", user_id)
        
        # Broadcast user removal
        await self._broadcast_user_removed(document_id, user_id)
    
    def get_document_users(self, document_id: str) -> List[UserPresence]:
        """Get all users in a document."""
        return list(self.active_users[document_id].values())
    
    def get_nearby_users(
        self,
        document_id: str,
        position: Point3D,
        radius: float
    ) -> List[Tuple[str, float]]:
        """
        Get users near a position in 3D space.
        
        Returns:
            List of (user_id, distance) tuples
        """
        nearby = []
        
        for user_id, (cursor_pos, _) in self.user_cursors[document_id].items():
            distance = position.distance_to(cursor_pos)
            if distance <= radius:
                nearby.append((user_id, distance))
        
        return sorted(nearby, key=lambda x: x[1])
    
    def _generate_user_color(self, user_id: str) -> str:
        """Generate a consistent color for a user."""
        # Use hash to generate consistent color
        hash_val = hash(user_id)
        hue = (hash_val % 360)
        # Use HSL with good saturation and lightness for visibility
        # Convert to hex (simplified - actual implementation would use proper HSL to RGB)
        r = int((hue / 360) * 255)
        g = int(((hue + 120) % 360 / 360) * 255)
        b = int(((hue + 240) % 360 / 360) * 255)
        return f"#{r:02x}{g:02x}{b:02x}"
    
    # Broadcast methods (would integrate with WebSocket manager)
    async def _broadcast_status_changes(
        self,
        document_id: str,
        user_ids: List[str],
        status: UserStatus
    ):
        """Broadcast status changes."""
        # This would integrate with the WebSocket manager
        logger.debug(f"Broadcasting status change for {user_ids} to {status}")
    
    async def _broadcast_cursor_update(
        self,
        document_id: str,
        user_id: str,
        position: Point3D,
        viewport: Optional[ViewportInfo]
    ):
        """Broadcast cursor position update."""
        logger.debug(f"Broadcasting cursor update for {user_id}")
    
    async def _broadcast_selection_update(
        self,
        document_id: str,
        user_id: str,
        selected_objects: List[str]
    ):
        """Broadcast selection update."""
        logger.debug(f"Broadcasting selection update for {user_id}: {selected_objects}")
    
    async def _broadcast_lock_update(
        self,
        document_id: str,
        object_id: str,
        user_id: str,
        lock_type: LockType
    ):
        """Broadcast lock acquisition."""
        logger.debug(f"Broadcasting lock update: {user_id} locked {object_id} ({lock_type})")
    
    async def _broadcast_lock_release(
        self,
        document_id: str,
        object_id: str,
        user_id: str
    ):
        """Broadcast lock release."""
        logger.debug(f"Broadcasting lock release: {user_id} released {object_id}")
    
    async def _broadcast_user_removed(self, document_id: str, user_id: str):
        """Broadcast user removal."""
        logger.debug(f"Broadcasting user removal: {user_id} left {document_id}")