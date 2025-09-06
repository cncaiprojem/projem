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
            
            # Prepare context for storage
            context_data = {
                **context,
                "operation_id": str(operation_id),
                "job_id": job_id,
                "timestamp": time.time()
            }
            
            # Store context with TTL
            key = OPERATION_CONTEXT_KEY.format(
                job_id=job_id,
                operation_id=str(operation_id)
            )
            await redis.setex(
                key,
                OPERATION_TTL,
                json.dumps(context_data, default=str)
            )
            
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
            data = await redis.get(key)
            
            if data:
                context = json.loads(data)
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
        context = await self.get_operation_context(job_id, operation_id)
        if not context:
            logger.warning(
                f"Operation {operation_id} not found for job {job_id}"
            )
            return False
        
        # Update context
        context.update(updates)
        context["last_updated"] = time.time()
        
        # Store updated context
        return await self.set_operation_context(job_id, operation_id, context)
    
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