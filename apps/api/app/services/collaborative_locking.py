"""
Collaborative Locking System for FreeCAD Model Objects.
Manages object-level locks with transaction support.
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


class LockType(str, Enum):
    """Types of locks."""
    EXCLUSIVE = "exclusive"  # Only one user can hold this lock
    SHARED = "shared"  # Multiple users can hold shared locks
    UPGRADE = "upgrade"  # Shared lock that can be upgraded to exclusive


class LockStatus(str, Enum):
    """Lock request status."""
    GRANTED = "granted"
    PENDING = "pending"
    DENIED = "denied"
    EXPIRED = "expired"
    RELEASED = "released"


@dataclass
class Lock:
    """Represents a lock on an object."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    object_id: str = None
    user_id: str = None
    lock_type: LockType = LockType.EXCLUSIVE
    status: LockStatus = LockStatus.PENDING
    acquired_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    transaction_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self) -> bool:
        """Check if lock has expired."""
        if self.expires_at and self.status == LockStatus.GRANTED:
            return datetime.now(UTC) > self.expires_at
        return False
    
    def is_active(self) -> bool:
        """Check if lock is currently active."""
        return self.status == LockStatus.GRANTED and not self.is_expired()
    
    def can_coexist_with(self, other: "Lock") -> bool:
        """Check if this lock can coexist with another."""
        # Expired locks don't conflict
        if self.is_expired() or other.is_expired():
            return True
        
        # Released locks don't conflict
        if self.status == LockStatus.RELEASED or other.status == LockStatus.RELEASED:
            return True
        
        # Same user can have multiple locks
        if self.user_id == other.user_id:
            return True
        
        # Shared locks can coexist
        if self.lock_type == LockType.SHARED and other.lock_type == LockType.SHARED:
            return True
        
        return False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "object_id": self.object_id,
            "user_id": self.user_id,
            "lock_type": self.lock_type.value,
            "status": self.status.value,
            "acquired_at": self.acquired_at.isoformat() if self.acquired_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "transaction_id": self.transaction_id,
            "metadata": self.metadata
        }


@dataclass
class LockRequest:
    """Request for acquiring a lock."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = None
    object_ids: List[str] = field(default_factory=list)
    lock_type: LockType = LockType.EXCLUSIVE
    timeout_seconds: int = 300
    wait_timeout_seconds: int = 30  # How long to wait for lock
    priority: int = 0  # Higher priority requests are processed first
    transaction_id: Optional[str] = None
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "object_ids": self.object_ids,
            "lock_type": self.lock_type.value,
            "timeout_seconds": self.timeout_seconds,
            "wait_timeout_seconds": self.wait_timeout_seconds,
            "priority": self.priority,
            "transaction_id": self.transaction_id,
            "requested_at": self.requested_at.isoformat()
        }


@dataclass
class LockResult:
    """Result of a lock acquisition attempt."""
    request_id: str
    acquired: List[str] = field(default_factory=list)  # Object IDs successfully locked
    failed: List[str] = field(default_factory=list)  # Object IDs that couldn't be locked
    pending: List[str] = field(default_factory=list)  # Object IDs pending lock
    locks: List[Lock] = field(default_factory=list)  # Actual lock objects
    success: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "acquired": self.acquired,
            "failed": self.failed,
            "pending": self.pending,
            "locks": [lock.to_dict() for lock in self.locks],
            "success": self.success,
            "metadata": self.metadata
        }


@dataclass
class Transaction:
    """Represents a locking transaction."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = None
    locks: List[Lock] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    committed: bool = False
    rolled_back: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def add_lock(self, lock: Lock):
        """Add a lock to the transaction."""
        lock.transaction_id = self.id
        self.locks.append(lock)
    
    def is_active(self) -> bool:
        """Check if transaction is still active."""
        return not self.committed and not self.rolled_back


class CollaborativeLocking:
    """
    Manages collaborative object locking with transaction support.
    """
    
    def __init__(self, redis_url: Optional[str] = None):
        self.object_locks: Dict[str, Dict[str, Lock]] = defaultdict(dict)  # document_id -> object_id -> Lock
        self.user_locks: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))  # document_id -> user_id -> object_ids
        self.lock_queue: Dict[str, List[LockRequest]] = defaultdict(list)  # document_id -> queue
        self.transactions: Dict[str, Transaction] = {}  # transaction_id -> Transaction
        self.deadlock_detector = DeadlockDetector()
        
        self.redis_url = redis_url or settings.REDIS_URL
        self.redis_client: Optional[aioredis.Redis] = None
        
        self._background_tasks: Set[asyncio.Task] = set()
        self._lock = asyncio.Lock()  # Internal lock for thread safety
    
    async def initialize(self):
        """Initialize the locking system."""
        # Connect to Redis for distributed locking
        if self.redis_url:
            self.redis_client = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
        
        # Start background tasks
        self._start_background_tasks()
        
        logger.info("Collaborative locking system initialized")
    
    async def shutdown(self):
        """Shutdown the locking system."""
        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
        
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        
        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()
        
        logger.info("Collaborative locking system shutdown")
    
    def _start_background_tasks(self):
        """Start background maintenance tasks."""
        # Clean up expired locks
        task = asyncio.create_task(self._cleanup_expired_locks_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        
        # Process lock queue
        task = asyncio.create_task(self._process_queue_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        
        # Detect deadlocks
        task = asyncio.create_task(self._deadlock_detection_loop())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
    
    async def _cleanup_expired_locks_loop(self):
        """Periodically clean up expired locks."""
        while True:
            try:
                await asyncio.sleep(5)  # Check every 5 seconds
                await self._cleanup_expired_locks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in lock cleanup loop: {e}")
    
    async def _process_queue_loop(self):
        """Process pending lock requests."""
        while True:
            try:
                await asyncio.sleep(1)  # Process every second
                await self._process_all_queues()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in queue processing loop: {e}")
    
    async def _deadlock_detection_loop(self):
        """Detect and resolve deadlocks."""
        while True:
            try:
                await asyncio.sleep(10)  # Check every 10 seconds
                await self._detect_and_resolve_deadlocks()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in deadlock detection loop: {e}")
    
    async def acquire_locks(
        self,
        document_id: str,
        request: LockRequest
    ) -> LockResult:
        """
        Acquire locks for multiple objects.
        
        Args:
            document_id: Document ID
            request: Lock request
            
        Returns:
            LockResult with acquired and failed locks
        """
        async with self._lock:
            result = LockResult(request_id=request.id)
            
            # Check if all requested locks are available
            can_acquire_all = True
            conflicts = []
            
            for obj_id in request.object_ids:
                current_lock = self.object_locks[document_id].get(obj_id)
                
                if current_lock and current_lock.is_active():
                    # Check if locks can coexist
                    test_lock = Lock(
                        object_id=obj_id,
                        user_id=request.user_id,
                        lock_type=request.lock_type
                    )
                    
                    if not current_lock.can_coexist_with(test_lock):
                        can_acquire_all = False
                        conflicts.append((obj_id, current_lock))
            
            if can_acquire_all:
                # Acquire all locks
                for obj_id in request.object_ids:
                    lock = await self._acquire_single_lock(
                        document_id,
                        obj_id,
                        request.user_id,
                        request.lock_type,
                        request.timeout_seconds,
                        request.transaction_id
                    )
                    
                    if lock:
                        result.acquired.append(obj_id)
                        result.locks.append(lock)
                    else:
                        result.failed.append(obj_id)
                
                result.success = len(result.failed) == 0
                
            else:
                # Can't acquire all - check wait timeout
                if request.wait_timeout_seconds > 0:
                    # Queue the request
                    self.lock_queue[document_id].append(request)
                    result.pending = request.object_ids
                    result.metadata["queued"] = True
                    result.metadata["conflicts"] = [
                        {"object_id": obj_id, "held_by": lock.user_id}
                        for obj_id, lock in conflicts
                    ]
                    
                    # Wait for locks with timeout
                    try:
                        await asyncio.wait_for(
                            self._wait_for_locks(document_id, request),
                            timeout=request.wait_timeout_seconds
                        )
                        # Retry after waiting
                        return await self.acquire_locks(document_id, request)
                    except asyncio.TimeoutError:
                        # Timeout waiting for locks
                        result.failed = request.object_ids
                        result.metadata["timeout"] = True
                else:
                    # No waiting - immediate failure
                    result.failed = request.object_ids
                    result.metadata["conflicts"] = [
                        {"object_id": obj_id, "held_by": lock.user_id}
                        for obj_id, lock in conflicts
                    ]
            
            return result
    
    async def _acquire_single_lock(
        self,
        document_id: str,
        object_id: str,
        user_id: str,
        lock_type: LockType,
        timeout_seconds: int,
        transaction_id: Optional[str] = None
    ) -> Optional[Lock]:
        """Acquire a single lock."""
        # Create lock
        lock = Lock(
            object_id=object_id,
            user_id=user_id,
            lock_type=lock_type,
            status=LockStatus.GRANTED,
            acquired_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(seconds=timeout_seconds),
            transaction_id=transaction_id
        )
        
        # Store lock
        self.object_locks[document_id][object_id] = lock
        self.user_locks[document_id][user_id].add(object_id)
        
        # Add to transaction if specified
        if transaction_id and transaction_id in self.transactions:
            self.transactions[transaction_id].add_lock(lock)
        
        # Store in Redis for distributed coordination
        if self.redis_client:
            await self._store_lock_in_redis(document_id, object_id, lock)
        
        logger.debug(f"Acquired {lock_type} lock on {object_id} for user {user_id}")
        
        return lock
    
    async def release_locks(
        self,
        document_id: str,
        user_id: str,
        object_ids: List[str]
    ) -> List[str]:
        """
        Release locks on specified objects.
        
        Returns:
            List of successfully released object IDs
        """
        async with self._lock:
            released = []
            
            for obj_id in object_ids:
                lock = self.object_locks[document_id].get(obj_id)
                
                if lock and lock.user_id == user_id and lock.is_active():
                    # Mark as released
                    lock.status = LockStatus.RELEASED
                    
                    # Remove from tracking
                    del self.object_locks[document_id][obj_id]
                    self.user_locks[document_id][user_id].discard(obj_id)
                    
                    # Remove from Redis
                    if self.redis_client:
                        await self._remove_lock_from_redis(document_id, obj_id)
                    
                    released.append(obj_id)
                    
                    logger.debug(f"Released lock on {obj_id} for user {user_id}")
            
            # Process queue for released objects
            if released:
                await self._process_queue_for_objects(document_id, released)
            
            return released
    
    async def release_all_user_locks(
        self,
        document_id: str,
        user_id: str
    ) -> List[str]:
        """Release all locks held by a user."""
        object_ids = list(self.user_locks[document_id][user_id])
        return await self.release_locks(document_id, user_id, object_ids)
    
    async def upgrade_lock(
        self,
        document_id: str,
        user_id: str,
        object_id: str
    ) -> bool:
        """
        Upgrade a shared lock to exclusive.
        
        Returns:
            True if upgrade successful, False otherwise
        """
        async with self._lock:
            lock = self.object_locks[document_id].get(object_id)
            
            if not lock or lock.user_id != user_id:
                return False
            
            if lock.lock_type == LockType.EXCLUSIVE:
                # Already exclusive
                return True
            
            if lock.lock_type in [LockType.SHARED, LockType.UPGRADE]:
                # Check if upgrade is possible (no other locks)
                can_upgrade = True
                
                # In a real implementation, would check for other shared locks
                # For now, assume upgrade is possible
                
                if can_upgrade:
                    lock.lock_type = LockType.EXCLUSIVE
                    lock.acquired_at = datetime.now(UTC)
                    
                    # Update in Redis
                    if self.redis_client:
                        await self._store_lock_in_redis(document_id, object_id, lock)
                    
                    logger.debug(f"Upgraded lock on {object_id} to exclusive for user {user_id}")
                    return True
            
            return False
    
    async def extend_lock(
        self,
        document_id: str,
        user_id: str,
        object_id: str,
        additional_seconds: int
    ) -> bool:
        """
        Extend the expiration time of a lock.
        
        Returns:
            True if extension successful, False otherwise
        """
        async with self._lock:
            lock = self.object_locks[document_id].get(object_id)
            
            if lock and lock.user_id == user_id and lock.is_active():
                # Extend expiration
                if lock.expires_at:
                    lock.expires_at += timedelta(seconds=additional_seconds)
                else:
                    lock.expires_at = datetime.now(UTC) + timedelta(seconds=additional_seconds)
                
                # Update in Redis
                if self.redis_client:
                    await self._store_lock_in_redis(document_id, object_id, lock)
                
                logger.debug(f"Extended lock on {object_id} by {additional_seconds} seconds")
                return True
            
            return False
    
    async def begin_transaction(
        self,
        document_id: str,
        user_id: str
    ) -> str:
        """
        Begin a locking transaction.
        
        Returns:
            Transaction ID
        """
        transaction = Transaction(user_id=user_id)
        self.transactions[transaction.id] = transaction
        
        logger.debug(f"Started transaction {transaction.id} for user {user_id}")
        
        return transaction.id
    
    async def commit_transaction(
        self,
        transaction_id: str
    ) -> bool:
        """
        Commit a transaction (keeps all locks).
        
        Returns:
            True if successful, False otherwise
        """
        if transaction_id not in self.transactions:
            return False
        
        transaction = self.transactions[transaction_id]
        
        if not transaction.is_active():
            return False
        
        transaction.committed = True
        
        # Remove transaction association from locks
        for lock in transaction.locks:
            lock.transaction_id = None
        
        logger.debug(f"Committed transaction {transaction_id}")
        
        return True
    
    async def rollback_transaction(
        self,
        document_id: str,
        transaction_id: str
    ) -> bool:
        """
        Rollback a transaction (releases all locks).
        
        Returns:
            True if successful, False otherwise
        """
        if transaction_id not in self.transactions:
            return False
        
        transaction = self.transactions[transaction_id]
        
        if not transaction.is_active():
            return False
        
        # Release all locks in transaction
        object_ids = [lock.object_id for lock in transaction.locks]
        await self.release_locks(document_id, transaction.user_id, object_ids)
        
        transaction.rolled_back = True
        
        logger.debug(f"Rolled back transaction {transaction_id}")
        
        return True
    
    async def _wait_for_locks(
        self,
        document_id: str,
        request: LockRequest
    ):
        """Wait for locks to become available."""
        while True:
            # Check if locks are available
            all_available = True
            
            for obj_id in request.object_ids:
                lock = self.object_locks[document_id].get(obj_id)
                if lock and lock.is_active():
                    test_lock = Lock(
                        object_id=obj_id,
                        user_id=request.user_id,
                        lock_type=request.lock_type
                    )
                    if not lock.can_coexist_with(test_lock):
                        all_available = False
                        break
            
            if all_available:
                # Remove from queue
                if request in self.lock_queue[document_id]:
                    self.lock_queue[document_id].remove(request)
                return
            
            # Wait a bit before checking again
            await asyncio.sleep(0.1)
    
    async def _cleanup_expired_locks(self):
        """Clean up expired locks."""
        for doc_id, locks in list(self.object_locks.items()):
            expired = []
            
            for obj_id, lock in list(locks.items()):
                if lock.is_expired():
                    expired.append((obj_id, lock.user_id))
            
            # Release expired locks
            for obj_id, user_id in expired:
                await self.release_locks(doc_id, user_id, [obj_id])
                logger.info(f"Cleaned up expired lock on {obj_id}")
    
    async def _process_all_queues(self):
        """Process all document lock queues."""
        for doc_id in list(self.lock_queue.keys()):
            await self._process_queue(doc_id)
    
    async def _process_queue(self, document_id: str):
        """Process pending lock requests for a document."""
        if document_id not in self.lock_queue:
            return
        
        queue = self.lock_queue[document_id]
        if not queue:
            return
        
        # Sort by priority (higher first) and request time
        queue.sort(key=lambda r: (-r.priority, r.requested_at))
        
        processed = []
        
        for request in queue:
            # Try to acquire locks
            result = await self.acquire_locks(document_id, request)
            
            if result.success or len(result.failed) > 0:
                # Either succeeded or definitively failed
                processed.append(request)
        
        # Remove processed requests
        for request in processed:
            if request in queue:
                queue.remove(request)
    
    async def _process_queue_for_objects(
        self,
        document_id: str,
        object_ids: List[str]
    ):
        """Process queue for specific released objects."""
        if document_id not in self.lock_queue:
            return
        
        queue = self.lock_queue[document_id]
        
        for request in list(queue):
            # Check if request involves any released objects
            if any(obj_id in request.object_ids for obj_id in object_ids):
                # Try to acquire locks
                result = await self.acquire_locks(document_id, request)
                
                if result.success:
                    # Remove from queue
                    queue.remove(request)
    
    async def _detect_and_resolve_deadlocks(self):
        """Detect and resolve deadlocks."""
        for doc_id in self.object_locks.keys():
            deadlocks = self.deadlock_detector.detect_deadlocks(
                self.object_locks[doc_id],
                self.lock_queue.get(doc_id, [])
            )
            
            if deadlocks:
                logger.warning(f"Detected {len(deadlocks)} deadlocks in document {doc_id}")
                
                for deadlock in deadlocks:
                    await self._resolve_deadlock(doc_id, deadlock)
    
    async def _resolve_deadlock(
        self,
        document_id: str,
        deadlock: Dict[str, Any]
    ):
        """Resolve a detected deadlock."""
        # Simple resolution: release lock with lowest priority
        victim = deadlock.get("victim")
        
        if victim:
            user_id = victim.get("user_id")
            object_ids = victim.get("object_ids", [])
            
            if user_id and object_ids:
                await self.release_locks(document_id, user_id, object_ids)
                logger.info(f"Resolved deadlock by releasing locks for user {user_id}")
    
    async def _store_lock_in_redis(
        self,
        document_id: str,
        object_id: str,
        lock: Lock
    ):
        """Store lock in Redis for distributed coordination."""
        if not self.redis_client:
            return
        
        key = f"lock:{document_id}:{object_id}"
        value = json.dumps(lock.to_dict())
        
        # Set with expiration
        ttl = None
        if lock.expires_at:
            ttl = int((lock.expires_at - datetime.now(UTC)).total_seconds())
        
        if ttl and ttl > 0:
            await self.redis_client.set(key, value, ex=ttl)
        else:
            await self.redis_client.set(key, value)
    
    async def _remove_lock_from_redis(
        self,
        document_id: str,
        object_id: str
    ):
        """Remove lock from Redis."""
        if not self.redis_client:
            return
        
        key = f"lock:{document_id}:{object_id}"
        await self.redis_client.delete(key)
    
    def get_lock_status(
        self,
        document_id: str,
        object_id: str
    ) -> Optional[Lock]:
        """Get current lock status for an object."""
        return self.object_locks[document_id].get(object_id)
    
    def get_user_locks(
        self,
        document_id: str,
        user_id: str
    ) -> List[Lock]:
        """Get all locks held by a user."""
        locks = []
        
        for obj_id in self.user_locks[document_id][user_id]:
            lock = self.object_locks[document_id].get(obj_id)
            if lock and lock.is_active():
                locks.append(lock)
        
        return locks
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get locking statistics."""
        total_locks = sum(
            len(locks) for locks in self.object_locks.values()
        )
        
        total_queued = sum(
            len(queue) for queue in self.lock_queue.values()
        )
        
        lock_type_counts = {}
        user_lock_counts = {}
        
        for doc_locks in self.object_locks.values():
            for lock in doc_locks.values():
                if lock.is_active():
                    # Count by type
                    lock_type = lock.lock_type.value
                    lock_type_counts[lock_type] = lock_type_counts.get(lock_type, 0) + 1
                    
                    # Count by user
                    user_lock_counts[lock.user_id] = user_lock_counts.get(lock.user_id, 0) + 1
        
        return {
            "total_active_locks": total_locks,
            "total_queued_requests": total_queued,
            "active_transactions": len([t for t in self.transactions.values() if t.is_active()]),
            "lock_type_distribution": lock_type_counts,
            "locks_by_user": user_lock_counts
        }


class DeadlockDetector:
    """Detects deadlocks in lock requests."""
    
    def detect_deadlocks(
        self,
        locks: Dict[str, Lock],
        queue: List[LockRequest]
    ) -> List[Dict[str, Any]]:
        """
        Detect deadlocks using wait-for graph.
        
        Returns:
            List of detected deadlocks
        """
        # Build wait-for graph
        wait_graph = defaultdict(set)
        
        for request in queue:
            waiting_user = request.user_id
            
            for obj_id in request.object_ids:
                if obj_id in locks:
                    lock = locks[obj_id]
                    if lock.is_active() and lock.user_id != waiting_user:
                        # User is waiting for lock held by another user
                        wait_graph[waiting_user].add(lock.user_id)
        
        # Find cycles in wait-for graph
        deadlocks = []
        visited = set()
        
        for user in wait_graph:
            if user not in visited:
                cycle = self._find_cycle(user, wait_graph, visited, set())
                if cycle:
                    deadlocks.append({
                        "users": cycle,
                        "victim": {"user_id": cycle[0]}  # Simple victim selection
                    })
        
        return deadlocks
    
    def _find_cycle(
        self,
        node: str,
        graph: Dict[str, Set[str]],
        visited: Set[str],
        path: Set[str]
    ) -> Optional[List[str]]:
        """Find cycle in directed graph using DFS."""
        visited.add(node)
        path.add(node)
        
        for neighbor in graph.get(node, set()):
            if neighbor in path:
                # Found cycle
                return [neighbor, node]
            elif neighbor not in visited:
                cycle = self._find_cycle(neighbor, graph, visited, path)
                if cycle:
                    if node in cycle:
                        return cycle
                    else:
                        cycle.append(node)
                        return cycle
        
        path.remove(node)
        return None