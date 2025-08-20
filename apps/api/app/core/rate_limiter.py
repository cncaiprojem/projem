"""
Ultra-Enterprise Rate Limiter for API Protection

Implements rate limiting with:
- Token bucket algorithm
- Redis-backed storage for distributed systems
- In-memory fallback for development
- Per-user and per-IP limiting
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import structlog
import redis
from redis.exceptions import RedisError

logger = structlog.get_logger(__name__)


class RateLimiter:
    """
    Rate limiter using token bucket algorithm.
    
    Supports both Redis (production) and in-memory (development) backends.
    """
    
    def __init__(
        self,
        max_requests: int = 100,
        window_seconds: int = 60,
        redis_client: Optional[redis.Redis] = None,
        key_prefix: str = "rate_limit",
    ):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
            redis_client: Optional Redis client for distributed limiting
            key_prefix: Prefix for Redis keys
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.redis_client = redis_client
        self.key_prefix = key_prefix
        
        # In-memory storage for fallback
        self._memory_storage: Dict[str, Tuple[int, float]] = defaultdict(
            lambda: (0, time.time())
        )
        
        # Try to get Redis client from environment if not provided
        if not self.redis_client:
            try:
                import os
                redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                # Test connection
                self.redis_client.ping()
                logger.info(
                    "Rate limiter initialized with Redis",
                    max_requests=max_requests,
                    window_seconds=window_seconds,
                )
            except (RedisError, Exception) as e:
                logger.warning(
                    "Redis not available, using in-memory rate limiting",
                    error=str(e),
                )
                self.redis_client = None
    
    def check_rate_limit(self, key: str) -> bool:
        """
        Check if request is within rate limit.
        
        Args:
            key: Unique key for rate limiting (e.g., user_id, IP)
            
        Returns:
            bool: True if request is allowed, False if rate limited
        """
        if self.redis_client:
            return self._check_redis(key)
        else:
            return self._check_memory(key)
    
    def get_remaining(self, key: str) -> Tuple[int, int]:
        """
        Get remaining requests and reset time.
        
        Args:
            key: Unique key for rate limiting
            
        Returns:
            Tuple of (remaining_requests, seconds_until_reset)
        """
        if self.redis_client:
            return self._get_remaining_redis(key)
        else:
            return self._get_remaining_memory(key)
    
    def reset(self, key: str) -> None:
        """
        Reset rate limit for a key.
        
        Args:
            key: Key to reset
        """
        if self.redis_client:
            self._reset_redis(key)
        else:
            self._reset_memory(key)
    
    # Redis-based implementation
    
    def _check_redis(self, key: str) -> bool:
        """Check rate limit using Redis."""
        try:
            full_key = f"{self.key_prefix}:{key}"
            current_time = time.time()
            
            # Use Redis pipeline for atomic operations
            pipe = self.redis_client.pipeline()
            
            # Remove old entries outside the window
            min_time = current_time - self.window_seconds
            pipe.zremrangebyscore(full_key, 0, min_time)
            
            # Count current requests in window
            pipe.zcard(full_key)
            
            # Execute pipeline
            results = pipe.execute()
            current_count = results[1]
            
            # Check if under limit
            if current_count < self.max_requests:
                # Add new request
                pipe = self.redis_client.pipeline()
                pipe.zadd(full_key, {str(current_time): current_time})
                pipe.expire(full_key, self.window_seconds + 1)
                pipe.execute()
                
                logger.debug(
                    "Rate limit check passed (Redis)",
                    key=key,
                    current=current_count + 1,
                    max=self.max_requests,
                )
                return True
            else:
                logger.warning(
                    "Rate limit exceeded (Redis)",
                    key=key,
                    current=current_count,
                    max=self.max_requests,
                )
                return False
                
        except RedisError as e:
            logger.error(
                "Redis error in rate limiter, falling back to memory",
                error=str(e),
            )
            # Fallback to memory
            return self._check_memory(key)
    
    def _get_remaining_redis(self, key: str) -> Tuple[int, int]:
        """Get remaining requests from Redis."""
        try:
            full_key = f"{self.key_prefix}:{key}"
            current_time = time.time()
            min_time = current_time - self.window_seconds
            
            # Remove old entries and count current
            pipe = self.redis_client.pipeline()
            pipe.zremrangebyscore(full_key, 0, min_time)
            pipe.zcard(full_key)
            pipe.zrange(full_key, 0, 0, withscores=True)
            results = pipe.execute()
            
            current_count = results[1]
            oldest_entry = results[2]
            
            remaining = max(0, self.max_requests - current_count)
            
            if oldest_entry:
                oldest_time = oldest_entry[0][1]
                reset_time = int(oldest_time + self.window_seconds - current_time)
            else:
                reset_time = 0
            
            return remaining, max(0, reset_time)
            
        except RedisError:
            return self._get_remaining_memory(key)
    
    def _reset_redis(self, key: str) -> None:
        """Reset rate limit in Redis."""
        try:
            full_key = f"{self.key_prefix}:{key}"
            self.redis_client.delete(full_key)
            logger.info("Rate limit reset (Redis)", key=key)
        except RedisError:
            self._reset_memory(key)
    
    # In-memory implementation
    
    def _check_memory(self, key: str) -> bool:
        """Check rate limit using in-memory storage."""
        current_time = time.time()
        count, window_start = self._memory_storage[key]
        
        # Check if window has expired
        if current_time - window_start >= self.window_seconds:
            # Reset window
            self._memory_storage[key] = (1, current_time)
            logger.debug(
                "Rate limit check passed (Memory, new window)",
                key=key,
                current=1,
                max=self.max_requests,
            )
            return True
        
        # Check if under limit
        if count < self.max_requests:
            self._memory_storage[key] = (count + 1, window_start)
            logger.debug(
                "Rate limit check passed (Memory)",
                key=key,
                current=count + 1,
                max=self.max_requests,
            )
            return True
        else:
            logger.warning(
                "Rate limit exceeded (Memory)",
                key=key,
                current=count,
                max=self.max_requests,
            )
            return False
    
    def _get_remaining_memory(self, key: str) -> Tuple[int, int]:
        """Get remaining requests from memory."""
        current_time = time.time()
        count, window_start = self._memory_storage[key]
        
        # Check if window has expired
        if current_time - window_start >= self.window_seconds:
            return self.max_requests, 0
        
        remaining = max(0, self.max_requests - count)
        reset_time = int(window_start + self.window_seconds - current_time)
        
        return remaining, max(0, reset_time)
    
    def _reset_memory(self, key: str) -> None:
        """Reset rate limit in memory."""
        if key in self._memory_storage:
            del self._memory_storage[key]
            logger.info("Rate limit reset (Memory)", key=key)


# Global rate limiters for common use cases
api_rate_limiter = RateLimiter(
    max_requests=100,
    window_seconds=60,
    key_prefix="api",
)

upload_rate_limiter = RateLimiter(
    max_requests=10,
    window_seconds=60,
    key_prefix="upload",
)

download_rate_limiter = RateLimiter(
    max_requests=60,
    window_seconds=60,
    key_prefix="download",
)


__all__ = [
    "RateLimiter",
    "api_rate_limiter",
    "upload_rate_limiter",
    "download_rate_limiter",
]