"""
Task 7.16: Redis-based Operation Context Storage

This module provides distributed state management for operation contexts
using Redis, ensuring consistency across multiple API server processes.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional
from uuid import UUID

from ..core.logging import get_logger
from ..core.redis_config import get_async_redis_client

logger = get_logger(__name__)

# Redis key patterns
OPERATION_CONTEXT_KEY = "operation:context:{job_id}:{operation_id}"
OPERATION_LIST_KEY = "operation:list:{job_id}"
OPERATION_TTL = 3600  # 1 hour TTL for operation contexts

# Numeric fields that need type conversion when retrieving from Redis
# Using set for O(1) membership testing performance
NUMERIC_FIELDS = {
    'job_id', 'timestamp', 'last_updated',
    'total_steps', 'current_step', 'start_time',
    'step_index', 'step_total', 'elapsed_ms', 'eta_ms',
    'progress_pct', 'shapes_done', 'shapes_total',
    'bytes_written', 'bytes_total', 'constraints_resolved',
    'constraints_total', 'items_done', 'items_total',
    'lcs_resolved', 'lcs_total', 'solids_in', 'solids_out'
}


class RedisOperationStore:
    """
    Redis-based storage for operation contexts.
    
    Features:
    - Distributed state management
    - Automatic TTL cleanup
    - Thread-safe operations
    - Graceful fallback on Redis failures
    """
    
    def __init__(self):
        """Initialize Redis operation store."""
        self._redis_client = None
        self._fallback_store: Dict[int, Dict[str, Any]] = {}  # In-memory fallback
    
    async def _get_redis(self):
        """Get Redis client with lazy initialization."""
        if not self._redis_client:
            self._redis_client = await get_async_redis_client()
        return self._redis_client
    
    async def set_operation_context(
        self,
        job_id: int,
        operation_id: UUID,
        context: Dict[str, Any]
    ) -> bool:
        """
        Store operation context in Redis.
        
        Args:
            job_id: Job ID
            operation_id: Operation ID
            context: Operation context data
            
        Returns:
            True if stored successfully
        """
        try:
            redis = await self._get_redis()
            
            # Use Hash key for atomic operations
            key = OPERATION_CONTEXT_KEY.format(
                job_id=job_id,
                operation_id=str(operation_id)
            )
            
            # Prepare fields for Hash storage
            # Convert all values to strings for Redis Hash compatibility
            hash_fields = {
                "operation_id": str(operation_id),
                "job_id": str(job_id),
                "timestamp": str(time.time()),
                "last_updated": str(time.time())
            }
            
            # Add context fields, converting complex types to JSON strings
            for field_name, field_value in context.items():
                if isinstance(field_value, (dict, list)):
                    hash_fields[field_name] = json.dumps(field_value, default=str)
                else:
                    hash_fields[field_name] = str(field_value)
            
            # Store as Hash with atomic operation
            await redis.hset(key, mapping=hash_fields)
            await redis.expire(key, OPERATION_TTL)
            
            # Add to job's operation list
            list_key = OPERATION_LIST_KEY.format(job_id=job_id)
            await redis.sadd(list_key, str(operation_id))
            await redis.expire(list_key, OPERATION_TTL)
            
            logger.debug(
                f"Stored operation context for job {job_id}, "
                f"operation {operation_id}"
            )
            return True
            
        except Exception as e:
            logger.warning(
                f"Failed to store operation context in Redis: {e}",
                exc_info=True
            )
            
            # Fallback to in-memory storage
            if job_id not in self._fallback_store:
                self._fallback_store[job_id] = {}
            self._fallback_store[job_id][str(operation_id)] = context
            return False
    
    async def get_operation_context(
        self,
        job_id: int,
        operation_id: UUID
    ) -> Optional[Dict[str, Any]]:
        """
        Retrieve operation context from Redis.
        
        Args:
            job_id: Job ID
            operation_id: Operation ID
            
        Returns:
            Operation context or None if not found
        """
        try:
            redis = await self._get_redis()
            
            key = OPERATION_CONTEXT_KEY.format(
                job_id=job_id,
                operation_id=str(operation_id)
            )
            
            # Get all fields from Hash
            hash_data = await redis.hgetall(key)
            
            if hash_data:
                # Convert bytes to strings and parse JSON fields
                context = {}
                for field_name, field_value in hash_data.items():
                    # Decode bytes if necessary
                    if isinstance(field_name, bytes):
                        field_name = field_name.decode('utf-8')
                    if isinstance(field_value, bytes):
                        field_value = field_value.decode('utf-8')
                    
                    # Try to parse JSON for complex fields
                    if field_value.startswith(('{', '[')):
                        try:
                            context[field_name] = json.loads(field_value)
                        except json.JSONDecodeError:
                            context[field_name] = field_value
                    else:
                        # Convert numeric strings back to appropriate types
                        if field_name in NUMERIC_FIELDS:
                            try:
                                # Try int conversion first
                                context[field_name] = int(field_value)
                            except ValueError:
                                try:
                                    # Fall back to float if int fails
                                    context[field_name] = float(field_value)
                                except ValueError:
                                    # Keep as string if both conversions fail
                                    context[field_name] = field_value
                        else:
                            context[field_name] = field_value
                
                logger.debug(
                    f"Retrieved operation context for job {job_id}, "
                    f"operation {operation_id}"
                )
                return context
            
        except Exception as e:
            logger.warning(
                f"Failed to get operation context from Redis: {e}",
                exc_info=True
            )
            
            # Try fallback store
            if job_id in self._fallback_store:
                return self._fallback_store[job_id].get(str(operation_id))
        
        return None
    
    async def update_operation_context(
        self,
        job_id: int,
        operation_id: UUID,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update operation context in Redis.
        
        Args:
            job_id: Job ID
            operation_id: Operation ID
            updates: Fields to update
            
        Returns:
            True if updated successfully
        """
        try:
            redis = await self._get_redis()
            
            key = OPERATION_CONTEXT_KEY.format(
                job_id=job_id,
                operation_id=str(operation_id)
            )
            
            # Check if key exists
            if not await redis.exists(key):
                logger.warning(
                    f"Operation {operation_id} not found for job {job_id}"
                )
                return False
            
            # Prepare updates for Hash storage
            hash_updates = {"last_updated": str(time.time())}
            
            for field_name, field_value in updates.items():
                if isinstance(field_value, (dict, list)):
                    hash_updates[field_name] = json.dumps(field_value, default=str)
                else:
                    hash_updates[field_name] = str(field_value)
            
            # Atomic update using HSET
            await redis.hset(key, mapping=hash_updates)
            
            # Refresh TTL
            await redis.expire(key, OPERATION_TTL)
            
            logger.debug(
                f"Updated operation context for job {job_id}, "
                f"operation {operation_id}"
            )
            return True
            
        except Exception as e:
            logger.warning(
                f"Failed to update operation context in Redis: {e}",
                exc_info=True
            )
            
            # Fallback to in-memory update
            if job_id in self._fallback_store:
                if str(operation_id) in self._fallback_store[job_id]:
                    self._fallback_store[job_id][str(operation_id)].update(updates)
                    return True
            
            return False
    
    async def delete_operation_context(
        self,
        job_id: int,
        operation_id: UUID
    ) -> bool:
        """
        Delete operation context from Redis.
        
        Args:
            job_id: Job ID
            operation_id: Operation ID
            
        Returns:
            True if deleted successfully
        """
        try:
            redis = await self._get_redis()
            
            # Delete context
            key = OPERATION_CONTEXT_KEY.format(
                job_id=job_id,
                operation_id=str(operation_id)
            )
            await redis.delete(key)
            
            # Remove from job's operation list
            list_key = OPERATION_LIST_KEY.format(job_id=job_id)
            await redis.srem(list_key, str(operation_id))
            
            logger.debug(
                f"Deleted operation context for job {job_id}, "
                f"operation {operation_id}"
            )
            return True
            
        except Exception as e:
            logger.warning(
                f"Failed to delete operation context from Redis: {e}",
                exc_info=True
            )
            
            # Clean fallback store
            if job_id in self._fallback_store:
                self._fallback_store[job_id].pop(str(operation_id), None)
                if not self._fallback_store[job_id]:
                    del self._fallback_store[job_id]
            
            return False
    
    async def get_job_operations(self, job_id: int) -> list[str]:
        """
        Get all operation IDs for a job.
        
        Args:
            job_id: Job ID
            
        Returns:
            List of operation IDs
        """
        try:
            redis = await self._get_redis()
            
            list_key = OPERATION_LIST_KEY.format(job_id=job_id)
            operation_ids = await redis.smembers(list_key)
            
            return [op_id.decode() if isinstance(op_id, bytes) else op_id 
                    for op_id in operation_ids]
            
        except Exception as e:
            logger.warning(
                f"Failed to get job operations from Redis: {e}",
                exc_info=True
            )
            
            # Return from fallback store
            if job_id in self._fallback_store:
                return list(self._fallback_store[job_id].keys())
            
            return []
    
    async def cleanup_job_operations(self, job_id: int) -> int:
        """
        Clean up all operations for a job.
        
        Args:
            job_id: Job ID
            
        Returns:
            Number of operations cleaned up
        """
        operation_ids = await self.get_job_operations(job_id)
        count = 0
        
        for op_id in operation_ids:
            if await self.delete_operation_context(job_id, UUID(op_id)):
                count += 1
        
        logger.info(f"Cleaned up {count} operations for job {job_id}")
        return count


# Global instance
redis_operation_store = RedisOperationStore()