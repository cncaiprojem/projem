"""
Redis-based State Manager for Performance Profiling (Task 7.25)

This module provides centralized state management for performance profiling
in multi-worker deployments using Redis as the backend store.

Features:
- Shared state across multiple workers
- Atomic operations with Redis transactions
- TTL-based automatic cleanup
- JSON serialization for complex data structures
- Connection pooling and retry logic
- Turkish error message support
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set
from enum import Enum

import redis
from redis.exceptions import RedisError, ConnectionError, TimeoutError
from redis.lock import Lock as RedisLock

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core.telemetry import create_span
from ..middleware.correlation_middleware import get_correlation_id

logger = get_logger(__name__)


class StateKeyPrefix(str, Enum):
    """Redis key prefixes for different state types."""
    ACTIVE_PROFILERS = "profiling:active_profilers"
    ACTIVE_CONNECTIONS = "profiling:active_connections"
    MEMORY_SNAPSHOTS = "profiling:memory_snapshots"
    OPERATION_HISTORY = "profiling:operation_history"
    PERFORMANCE_METRICS = "profiling:performance_metrics"
    OPTIMIZATION_PLANS = "profiling:optimization_plans"
    PROFILE_STORAGE = "profiling:profiles"
    LOCK = "profiling:lock"


class ProfilingStateManager:
    """
    Manages profiling state in Redis for multi-worker deployments.

    Belirli işlem profilleme durumunu Redis'te yönetir.
    """

    def __init__(
        self,
        redis_url: Optional[str] = None,
        key_prefix: str = "freecad",
        ttl_seconds: int = 3600,
        max_retries: int = 3,
        retry_delay: float = 0.5
    ):
        """
        Initialize Redis-based state manager.

        Args:
            redis_url: Redis connection URL
            key_prefix: Prefix for all Redis keys
            ttl_seconds: Default TTL for state entries
            max_retries: Maximum retry attempts for Redis operations
            retry_delay: Delay between retries in seconds
        """
        self.redis_url = redis_url or getattr(settings, "REDIS_URL", "redis://localhost:6379/0")
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Initialize Redis connection pool
        self._redis_pool = redis.ConnectionPool.from_url(
            self.redis_url,
            max_connections=50,
            socket_keepalive=True,
            socket_keepalive_options={
                1: 1,  # TCP_KEEPIDLE
                2: 3,  # TCP_KEEPINTVL
                3: 5,  # TCP_KEEPCNT
            }
        )

        # Create Redis client
        self._redis_client = redis.Redis(
            connection_pool=self._redis_pool,
            decode_responses=False,  # We'll handle encoding/decoding
            socket_connect_timeout=5,
            socket_timeout=5
        )

        # Test connection
        try:
            self._redis_client.ping()
            logger.info("ProfilingStateManager connected to Redis", redis_url=self.redis_url)
        except RedisError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def _make_key(self, prefix: StateKeyPrefix, suffix: Optional[str] = None) -> str:
        """Generate Redis key with prefix and optional suffix."""
        parts = [self.key_prefix, prefix.value]
        if suffix:
            parts.append(suffix)
        return ":".join(parts)

    def _serialize(self, data: Any) -> bytes:
        """Serialize data to JSON bytes."""
        try:
            return json.dumps(data, default=str).encode('utf-8')
        except (TypeError, ValueError) as e:
            logger.error(f"Serialization error: {e}")
            raise

    def _deserialize(self, data: bytes) -> Any:
        """Deserialize JSON bytes to data."""
        if not data:
            return None
        try:
            return json.loads(data.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.error(f"Deserialization error: {e}")
            return None

    def _execute_with_retry(self, func, *args, **kwargs):
        """Execute Redis operation with retry logic."""
        last_error = None
        for attempt in range(self.max_retries):
            try:
                return func(*args, **kwargs)
            except (ConnectionError, TimeoutError) as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))
                    logger.warning(f"Redis operation failed, retrying... (attempt {attempt + 1})")
            except RedisError as e:
                logger.error(f"Redis operation failed: {e}")
                raise

        if last_error:
            raise last_error

    # Active profilers management

    def add_active_profiler(self, profile_id: str, profile_data: Dict[str, Any]) -> bool:
        """
        Add an active profiler to shared state.

        Args:
            profile_id: Unique profile ID
            profile_data: Profile metadata

        Returns:
            Success status
        """
        key = self._make_key(StateKeyPrefix.ACTIVE_PROFILERS, profile_id)
        profile_data['timestamp'] = time.time()

        try:
            return self._execute_with_retry(
                self._redis_client.setex,
                key,
                self.ttl_seconds,
                self._serialize(profile_data)
            )
        except Exception as e:
            logger.error(f"Failed to add active profiler: {e}")
            return False

    def remove_active_profiler(self, profile_id: str) -> bool:
        """Remove an active profiler from shared state."""
        key = self._make_key(StateKeyPrefix.ACTIVE_PROFILERS, profile_id)

        try:
            return self._execute_with_retry(self._redis_client.delete, key) > 0
        except Exception as e:
            logger.error(f"Failed to remove active profiler: {e}")
            return False

    def get_active_profilers(self) -> Dict[str, Dict[str, Any]]:
        """Get all active profilers across workers."""
        pattern = self._make_key(StateKeyPrefix.ACTIVE_PROFILERS, "*")

        try:
            profilers = {}
            cursor = 0

            while True:
                cursor, keys = self._execute_with_retry(
                    self._redis_client.scan,
                    cursor,
                    match=pattern,
                    count=100
                )

                if keys:
                    # Use pipeline for batch fetching
                    pipe = self._redis_client.pipeline()
                    for key in keys:
                        pipe.get(key)

                    values = self._execute_with_retry(pipe.execute)

                    for key, value in zip(keys, values):
                        if value:
                            # Extract profile_id from key
                            profile_id = key.decode('utf-8').split(':')[-1]
                            profilers[profile_id] = self._deserialize(value)

                if cursor == 0:
                    break

            return profilers

        except Exception as e:
            logger.error(f"Failed to get active profilers: {e}")
            return {}

    # WebSocket connections management

    def add_active_connection(self, connection_id: str, worker_id: str) -> bool:
        """Register an active WebSocket connection."""
        key = self._make_key(StateKeyPrefix.ACTIVE_CONNECTIONS)

        connection_data = {
            'connection_id': connection_id,
            'worker_id': worker_id,
            'timestamp': time.time()
        }

        try:
            return self._execute_with_retry(
                self._redis_client.hset,
                key,
                connection_id,
                self._serialize(connection_data)
            ) >= 0
        except Exception as e:
            logger.error(f"Failed to add active connection: {e}")
            return False

    def remove_active_connection(self, connection_id: str) -> bool:
        """Remove an active WebSocket connection."""
        key = self._make_key(StateKeyPrefix.ACTIVE_CONNECTIONS)

        try:
            return self._execute_with_retry(
                self._redis_client.hdel,
                key,
                connection_id
            ) > 0
        except Exception as e:
            logger.error(f"Failed to remove active connection: {e}")
            return False

    def get_active_connection_count(self) -> int:
        """Get count of active WebSocket connections across all workers."""
        key = self._make_key(StateKeyPrefix.ACTIVE_CONNECTIONS)

        try:
            return self._execute_with_retry(self._redis_client.hlen, key)
        except Exception as e:
            logger.error(f"Failed to get connection count: {e}")
            return 0

    # Memory snapshots management

    def add_memory_snapshot(self, snapshot_data: Dict[str, Any]) -> bool:
        """
        Add a memory snapshot to shared storage.

        Args:
            snapshot_data: Snapshot data

        Returns:
            Success status
        """
        key = self._make_key(StateKeyPrefix.MEMORY_SNAPSHOTS)
        snapshot_id = snapshot_data.get('snapshot_id', str(uuid.uuid4()))

        try:
            # Use Redis list with limited size
            pipe = self._redis_client.pipeline()
            pipe.lpush(key, self._serialize(snapshot_data))
            pipe.ltrim(key, 0, 99)  # Keep last 100 snapshots
            pipe.expire(key, 86400)  # 24 hour TTL

            results = self._execute_with_retry(pipe.execute)
            return all(results)

        except Exception as e:
            logger.error(f"Failed to add memory snapshot: {e}")
            return False

    def get_memory_snapshots(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent memory snapshots."""
        key = self._make_key(StateKeyPrefix.MEMORY_SNAPSHOTS)

        try:
            raw_snapshots = self._execute_with_retry(
                self._redis_client.lrange,
                key,
                0,
                limit - 1
            )

            snapshots = []
            for raw in raw_snapshots:
                snapshot = self._deserialize(raw)
                if snapshot:
                    snapshots.append(snapshot)

            return snapshots

        except Exception as e:
            logger.error(f"Failed to get memory snapshots: {e}")
            return []

    # Operation history management

    def add_operation_history(self, operation_data: Dict[str, Any]) -> bool:
        """Add operation to history for metrics calculation."""
        key = self._make_key(StateKeyPrefix.OPERATION_HISTORY)

        operation_data['timestamp'] = time.time()

        try:
            # Use Redis sorted set with timestamp as score
            return self._execute_with_retry(
                self._redis_client.zadd,
                key,
                {self._serialize(operation_data): operation_data['timestamp']}
            ) > 0

        except Exception as e:
            logger.error(f"Failed to add operation history: {e}")
            return False

    def get_recent_operations(self, seconds: int = 60) -> List[Dict[str, Any]]:
        """Get operations from last N seconds."""
        key = self._make_key(StateKeyPrefix.OPERATION_HISTORY)

        min_timestamp = time.time() - seconds

        try:
            # Get operations with score (timestamp) >= min_timestamp
            raw_operations = self._execute_with_retry(
                self._redis_client.zrangebyscore,
                key,
                min_timestamp,
                '+inf'
            )

            operations = []
            for raw in raw_operations:
                op = self._deserialize(raw)
                if op:
                    operations.append(op)

            # Clean up old entries
            self._execute_with_retry(
                self._redis_client.zremrangebyscore,
                key,
                '-inf',
                min_timestamp - 3600  # Remove entries older than 1 hour
            )

            return operations

        except Exception as e:
            logger.error(f"Failed to get recent operations: {e}")
            return []

    # Performance metrics storage

    def store_performance_metrics(self, metrics: Dict[str, Any]) -> bool:
        """Store performance metrics snapshot."""
        key = self._make_key(StateKeyPrefix.PERFORMANCE_METRICS)

        metrics['timestamp'] = time.time()

        try:
            # Use time-series approach with Redis sorted set
            return self._execute_with_retry(
                self._redis_client.zadd,
                key,
                {self._serialize(metrics): metrics['timestamp']}
            ) > 0

        except Exception as e:
            logger.error(f"Failed to store performance metrics: {e}")
            return False

    def get_performance_metrics(self, minutes: int = 5) -> List[Dict[str, Any]]:
        """Get performance metrics from last N minutes."""
        key = self._make_key(StateKeyPrefix.PERFORMANCE_METRICS)

        min_timestamp = time.time() - (minutes * 60)

        try:
            raw_metrics = self._execute_with_retry(
                self._redis_client.zrangebyscore,
                key,
                min_timestamp,
                '+inf'
            )

            metrics = []
            for raw in raw_metrics:
                metric = self._deserialize(raw)
                if metric:
                    metrics.append(metric)

            return metrics

        except Exception as e:
            logger.error(f"Failed to get performance metrics: {e}")
            return []

    # Distributed locking

    def acquire_lock(self, resource: str, timeout: int = 10) -> Optional[RedisLock]:
        """
        Acquire a distributed lock.

        Args:
            resource: Resource identifier
            timeout: Lock timeout in seconds

        Returns:
            Redis lock object or None
        """
        lock_key = self._make_key(StateKeyPrefix.LOCK, resource)

        try:
            lock = RedisLock(
                self._redis_client,
                lock_key,
                timeout=timeout,
                sleep=0.1,
                blocking=True,
                blocking_timeout=5
            )

            if lock.acquire(blocking=True, blocking_timeout=5):
                return lock

            return None

        except Exception as e:
            logger.error(f"Failed to acquire lock: {e}")
            return None

    def release_lock(self, lock: RedisLock) -> bool:
        """Release a distributed lock."""
        try:
            lock.release()
            return True
        except Exception as e:
            logger.error(f"Failed to release lock: {e}")
            return False

    # Profile storage methods for multi-worker consistency

    def add_cpu_profile(self, profile_data: Dict[str, Any]) -> bool:
        """Add CPU profile to shared storage."""
        key = self._make_key(StateKeyPrefix.PROFILE_STORAGE, "cpu")
        profile_data['timestamp'] = time.time()

        try:
            # Use Redis list with limited size
            pipe = self._redis_client.pipeline()
            pipe.lpush(key, self._serialize(profile_data))
            pipe.ltrim(key, 0, 99)  # Keep last 100 profiles
            pipe.expire(key, 86400)  # 24 hour TTL

            results = self._execute_with_retry(pipe.execute)
            return all(results)
        except Exception as e:
            logger.error(f"Failed to add CPU profile: {e}")
            return False

    def get_cpu_profiles(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent CPU profiles."""
        key = self._make_key(StateKeyPrefix.PROFILE_STORAGE, "cpu")

        try:
            raw_profiles = self._execute_with_retry(
                self._redis_client.lrange,
                key,
                0,
                limit - 1
            )

            profiles = []
            for raw in raw_profiles:
                profile = self._deserialize(raw)
                if profile:
                    profiles.append(profile)

            return profiles
        except Exception as e:
            logger.error(f"Failed to get CPU profiles: {e}")
            return []

    def add_memory_profile(self, profile_data: Dict[str, Any]) -> bool:
        """Add memory profile to shared storage."""
        key = self._make_key(StateKeyPrefix.PROFILE_STORAGE, "memory")
        profile_data['timestamp'] = time.time()

        try:
            # Use Redis list with limited size
            pipe = self._redis_client.pipeline()
            pipe.lpush(key, self._serialize(profile_data))
            pipe.ltrim(key, 0, 99)  # Keep last 100 profiles
            pipe.expire(key, 86400)  # 24 hour TTL

            results = self._execute_with_retry(pipe.execute)
            return all(results)
        except Exception as e:
            logger.error(f"Failed to add memory profile: {e}")
            return False

    def get_memory_profiles(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent memory profiles."""
        key = self._make_key(StateKeyPrefix.PROFILE_STORAGE, "memory")

        try:
            raw_profiles = self._execute_with_retry(
                self._redis_client.lrange,
                key,
                0,
                limit - 1
            )

            profiles = []
            for raw in raw_profiles:
                profile = self._deserialize(raw)
                if profile:
                    profiles.append(profile)

            return profiles
        except Exception as e:
            logger.error(f"Failed to get memory profiles: {e}")
            return []

    def add_gpu_profile(self, profile_data: Dict[str, Any]) -> bool:
        """Add GPU profile to shared storage."""
        key = self._make_key(StateKeyPrefix.PROFILE_STORAGE, "gpu")
        profile_data['timestamp'] = time.time()

        try:
            # Use Redis list with limited size
            pipe = self._redis_client.pipeline()
            pipe.lpush(key, self._serialize(profile_data))
            pipe.ltrim(key, 0, 99)  # Keep last 100 profiles
            pipe.expire(key, 86400)  # 24 hour TTL

            results = self._execute_with_retry(pipe.execute)
            return all(results)
        except Exception as e:
            logger.error(f"Failed to add GPU profile: {e}")
            return False

    def get_gpu_profiles(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent GPU profiles."""
        key = self._make_key(StateKeyPrefix.PROFILE_STORAGE, "gpu")

        try:
            raw_profiles = self._execute_with_retry(
                self._redis_client.lrange,
                key,
                0,
                limit - 1
            )

            profiles = []
            for raw in raw_profiles:
                profile = self._deserialize(raw)
                if profile:
                    profiles.append(profile)

            return profiles
        except Exception as e:
            logger.error(f"Failed to get GPU profiles: {e}")
            return []

    # FreeCAD operation storage

    def add_active_freecad_operation(self, operation_id: str, operation_data: Dict[str, Any]) -> bool:
        """Add active FreeCAD operation."""
        key = self._make_key(StateKeyPrefix.OPERATION_HISTORY, f"active_{operation_id}")
        operation_data['timestamp'] = time.time()

        try:
            return self._execute_with_retry(
                self._redis_client.setex,
                key,
                300,  # 5 minute TTL for active operations
                self._serialize(operation_data)
            )
        except Exception as e:
            logger.error(f"Failed to add active FreeCAD operation: {e}")
            return False

    def remove_active_freecad_operation(self, operation_id: str) -> bool:
        """Remove active FreeCAD operation."""
        key = self._make_key(StateKeyPrefix.OPERATION_HISTORY, f"active_{operation_id}")

        try:
            return self._execute_with_retry(self._redis_client.delete, key) > 0
        except Exception as e:
            logger.error(f"Failed to remove active FreeCAD operation: {e}")
            return False

    def get_active_freecad_operations(self) -> Dict[str, Dict[str, Any]]:
        """Get all active FreeCAD operations."""
        pattern = self._make_key(StateKeyPrefix.OPERATION_HISTORY, "active_*")

        try:
            operations = {}
            cursor = 0

            while True:
                cursor, keys = self._execute_with_retry(
                    self._redis_client.scan,
                    cursor,
                    match=pattern,
                    count=100
                )

                if keys:
                    # Use pipeline for batch fetching
                    pipe = self._redis_client.pipeline()
                    for key in keys:
                        pipe.get(key)

                    values = self._execute_with_retry(pipe.execute)

                    for key, value in zip(keys, values):
                        if value:
                            # Extract operation_id from key
                            operation_id = key.decode('utf-8').split('active_')[-1]
                            operations[operation_id] = self._deserialize(value)

                if cursor == 0:
                    break

            return operations
        except Exception as e:
            logger.error(f"Failed to get active FreeCAD operations: {e}")
            return {}

    def add_completed_freecad_operation(self, operation_data: Dict[str, Any]) -> bool:
        """Add completed FreeCAD operation."""
        key = self._make_key(StateKeyPrefix.OPERATION_HISTORY, "completed")
        operation_data['timestamp'] = time.time()

        try:
            # Use Redis list with limited size
            pipe = self._redis_client.pipeline()
            pipe.lpush(key, self._serialize(operation_data))
            pipe.ltrim(key, 0, 999)  # Keep last 1000 operations
            pipe.expire(key, 86400)  # 24 hour TTL

            results = self._execute_with_retry(pipe.execute)
            return all(results)
        except Exception as e:
            logger.error(f"Failed to add completed FreeCAD operation: {e}")
            return False

    def get_completed_freecad_operations(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get completed FreeCAD operations."""
        key = self._make_key(StateKeyPrefix.OPERATION_HISTORY, "completed")

        try:
            raw_operations = self._execute_with_retry(
                self._redis_client.lrange,
                key,
                0,
                limit - 1
            )

            operations = []
            for raw in raw_operations:
                operation = self._deserialize(raw)
                if operation:
                    operations.append(operation)

            return operations
        except Exception as e:
            logger.error(f"Failed to get completed FreeCAD operations: {e}")
            return []

    # Memory leak detection storage

    def add_detected_leak(self, leak_data: Dict[str, Any]) -> bool:
        """Add detected memory leak."""
        key = self._make_key(StateKeyPrefix.MEMORY_SNAPSHOTS, "leaks")
        leak_data['timestamp'] = time.time()

        try:
            # Use Redis list with limited size
            pipe = self._redis_client.pipeline()
            pipe.lpush(key, self._serialize(leak_data))
            pipe.ltrim(key, 0, 99)  # Keep last 100 leaks
            pipe.expire(key, 86400)  # 24 hour TTL

            results = self._execute_with_retry(pipe.execute)
            return all(results)
        except Exception as e:
            logger.error(f"Failed to add detected leak: {e}")
            return False

    def get_detected_leaks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get detected memory leaks."""
        key = self._make_key(StateKeyPrefix.MEMORY_SNAPSHOTS, "leaks")

        try:
            raw_leaks = self._execute_with_retry(
                self._redis_client.lrange,
                key,
                0,
                limit - 1
            )

            leaks = []
            for raw in raw_leaks:
                leak = self._deserialize(raw)
                if leak:
                    leaks.append(leak)

            return leaks
        except Exception as e:
            logger.error(f"Failed to get detected leaks: {e}")
            return []

    # Fragmentation analysis storage

    def add_fragmentation_analysis(self, analysis_data: Dict[str, Any]) -> bool:
        """Add fragmentation analysis."""
        key = self._make_key(StateKeyPrefix.MEMORY_SNAPSHOTS, "fragmentation")
        analysis_data['timestamp'] = time.time()

        try:
            # Use Redis list with limited size
            pipe = self._redis_client.pipeline()
            pipe.lpush(key, self._serialize(analysis_data))
            pipe.ltrim(key, 0, 49)  # Keep last 50 analyses
            pipe.expire(key, 86400)  # 24 hour TTL

            results = self._execute_with_retry(pipe.execute)
            return all(results)
        except Exception as e:
            logger.error(f"Failed to add fragmentation analysis: {e}")
            return False

    def get_fragmentation_analyses(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get fragmentation analyses."""
        key = self._make_key(StateKeyPrefix.MEMORY_SNAPSHOTS, "fragmentation")

        try:
            raw_analyses = self._execute_with_retry(
                self._redis_client.lrange,
                key,
                0,
                limit - 1
            )

            analyses = []
            for raw in raw_analyses:
                analysis = self._deserialize(raw)
                if analysis:
                    analyses.append(analysis)

            return analyses
        except Exception as e:
            logger.error(f"Failed to get fragmentation analyses: {e}")
            return []

    # Cleanup methods

    def cleanup_expired_data(self) -> Dict[str, int]:
        """Clean up expired data from Redis."""
        cleanup_stats = {}

        # Clean old profilers
        pattern = self._make_key(StateKeyPrefix.ACTIVE_PROFILERS, "*")
        deleted = 0

        try:
            cursor = 0
            while True:
                cursor, keys = self._execute_with_retry(
                    self._redis_client.scan,
                    cursor,
                    match=pattern,
                    count=100
                )

                if keys:
                    # Check TTL and delete expired
                    for key in keys:
                        ttl = self._execute_with_retry(self._redis_client.ttl, key)
                        if ttl < 0:  # No TTL set or expired
                            if self._execute_with_retry(self._redis_client.delete, key):
                                deleted += 1

                if cursor == 0:
                    break

            cleanup_stats['expired_profilers'] = deleted

        except Exception as e:
            logger.error(f"Cleanup failed: {e}")

        return cleanup_stats

    def get_state_summary(self) -> Dict[str, Any]:
        """Get summary of current state."""
        try:
            return {
                'active_profilers': len(self.get_active_profilers()),
                'active_connections': self.get_active_connection_count(),
                'memory_snapshots': len(self.get_memory_snapshots(10)),
                'recent_operations': len(self.get_recent_operations(60)),
                'redis_info': self._execute_with_retry(self._redis_client.info, 'memory')
            }
        except Exception as e:
            logger.error(f"Failed to get state summary: {e}")
            return {}

    def close(self):
        """Close Redis connections."""
        try:
            self._redis_pool.disconnect()
            logger.info("ProfilingStateManager closed Redis connections")
        except Exception as e:
            logger.error(f"Error closing Redis connections: {e}")


# Global state manager instance
state_manager = ProfilingStateManager()