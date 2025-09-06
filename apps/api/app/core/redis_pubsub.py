"""
Task 7.16: Redis Pub/Sub Integration for Real-time Progress

This module provides Redis pub/sub functionality for:
- Publishing progress updates from workers
- Subscribing to job progress channels
- Message serialization and deserialization
- Connection pooling and error handling
- Throttling and deduplication
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional, Set
from uuid import UUID

import redis.asyncio as redis_async
import redis
from redis.asyncio.client import PubSub

from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..schemas.progress import ProgressMessageV2

logger = get_logger(__name__)


class RedisProgressPubSub:
    """Redis pub/sub manager for progress updates."""
    
    # Channel patterns
    PROGRESS_CHANNEL_PREFIX = "job:progress:"
    PROGRESS_ALL_CHANNEL = "job:progress:*"
    
    # Throttling configuration
    THROTTLE_INTERVAL_MS = 500  # Max 1 update per 500ms per job
    MILESTONE_BYPASS = True  # Milestone events bypass throttling
    
    def __init__(self, redis_url: Optional[str] = None):
        """
        Initialize Redis pub/sub manager.
        
        Args:
            redis_url: Redis connection URL (defaults to settings)
        """
        self.redis_url = redis_url or settings.redis_url
        self._redis_client: Optional[redis_async.Redis] = None
        self._pubsub_clients: Dict[int, PubSub] = {}
        self._last_publish_times: Dict[int, float] = {}
        self._event_counters: Dict[int, int] = {}
        
    async def connect(self) -> None:
        """Establish Redis connection."""
        if not self._redis_client:
            try:
                self._redis_client = redis_async.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    max_connections=50,
                    socket_keepalive=True,
                    socket_keepalive_options={
                        1: 1,  # TCP_KEEPIDLE
                        2: 1,  # TCP_KEEPINTVL
                        3: 3,  # TCP_KEEPCNT
                    }
                )
                await self._redis_client.ping()
                logger.info("Redis pub/sub connection established")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise
    
    async def disconnect(self) -> None:
        """Close Redis connections."""
        # Close all pubsub clients
        for client in self._pubsub_clients.values():
            await client.close()
        self._pubsub_clients.clear()
        
        # Close main client
        if self._redis_client:
            await self._redis_client.close()
            self._redis_client = None
        
        logger.info("Redis pub/sub connections closed")
    
    def _get_channel_name(self, job_id: int) -> str:
        """Get channel name for a job."""
        return f"{self.PROGRESS_CHANNEL_PREFIX}{job_id}"
    
    def _should_throttle(self, job_id: int, is_milestone: bool) -> bool:
        """
        Check if message should be throttled.
        
        Args:
            job_id: Job ID
            is_milestone: Whether this is a milestone event
            
        Returns:
            True if message should be throttled (not sent)
        """
        if is_milestone and self.MILESTONE_BYPASS:
            return False
        
        now = time.time() * 1000  # Convert to milliseconds
        last_time = self._last_publish_times.get(job_id, 0)
        
        if now - last_time < self.THROTTLE_INTERVAL_MS:
            return True
        
        self._last_publish_times[job_id] = now
        return False
    
    def _get_next_event_id(self, job_id: int) -> int:
        """Get next monotonic event ID for a job."""
        self._event_counters[job_id] = self._event_counters.get(job_id, 0) + 1
        return self._event_counters[job_id]
    
    async def publish_progress(
        self,
        job_id: int,
        progress: ProgressMessageV2,
        force: bool = False
    ) -> bool:
        """
        Publish progress update to Redis channel.
        
        Args:
            job_id: Job ID
            progress: Progress message
            force: Force publish even if throttled
            
        Returns:
            True if published, False if throttled
        """
        if not self._redis_client:
            await self.connect()
        
        # Check throttling
        if not force and self._should_throttle(job_id, progress.milestone):
            logger.debug(f"Progress update throttled for job {job_id}")
            return False
        
        # Set event ID if not set
        if progress.event_id is None:
            progress.event_id = self._get_next_event_id(job_id)
        
        # Ensure job_id matches
        progress.job_id = job_id
        
        try:
            # Serialize message
            message = progress.model_dump_json()
            
            # Publish to channel
            channel = self._get_channel_name(job_id)
            subscribers = await self._redis_client.publish(channel, message)
            
            logger.debug(
                f"Published progress to {channel}: event_id={progress.event_id}, "
                f"type={progress.event_type}, subscribers={subscribers}"
            )
            
            # Also publish to wildcard channel for monitoring
            await self._redis_client.publish(self.PROGRESS_ALL_CHANNEL, message)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish progress for job {job_id}: {e}", exc_info=True)
            return False
    
    @asynccontextmanager
    async def subscribe_to_job(
        self,
        job_id: int,
        last_event_id: Optional[int] = None
    ) -> AsyncGenerator[PubSub, None]:
        """
        Subscribe to job progress updates.
        
        Args:
            job_id: Job ID to subscribe to
            last_event_id: Last event ID for resumption
            
        Yields:
            PubSub client for receiving messages
        """
        if not self._redis_client:
            await self.connect()
        
        pubsub = self._redis_client.pubsub()
        channel = self._get_channel_name(job_id)
        
        try:
            # Subscribe to channel
            await pubsub.subscribe(channel)
            logger.info(f"Subscribed to progress channel: {channel}")
            
            # Store client for cleanup
            self._pubsub_clients[job_id] = pubsub
            
            # If resuming, fetch missed events from cache
            if last_event_id is not None:
                await self._send_missed_events(pubsub, job_id, last_event_id)
            
            yield pubsub
            
        finally:
            # Unsubscribe and cleanup
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            self._pubsub_clients.pop(job_id, None)
            logger.info(f"Unsubscribed from progress channel: {channel}")
    
    async def get_missed_events(
        self,
        job_id: int,
        last_event_id: int
    ) -> List[str]:
        """
        Get missed events from cache for SSE resumption.
        
        Args:
            job_id: Job ID
            last_event_id: Last received event ID
            
        Returns:
            List of missed event JSON strings
        """
        # Get cached events from Redis sorted set
        cache_key = f"job:progress:cache:{job_id}"
        events = []
        
        try:
            # Get events with ID > last_event_id
            events = await self._redis_client.zrangebyscore(
                cache_key,
                min=last_event_id + 1,
                max="+inf",
                withscores=False
            )
            
            logger.info(
                f"Retrieved {len(events)} missed events for job {job_id} "
                f"(after event_id={last_event_id})"
            )
            
        except Exception as e:
            logger.warning(f"Failed to get missed events: {e}")
        
        return events
    
    async def _send_missed_events(
        self,
        pubsub: PubSub,
        job_id: int,
        last_event_id: int
    ) -> List[str]:
        """
        DEPRECATED: Use get_missed_events() instead.
        Kept for backward compatibility - returns missed events.
        
        Args:
            pubsub: PubSub client (unused)
            job_id: Job ID
            last_event_id: Last received event ID
            
        Returns:
            List of missed event JSON strings
        """
        return await self.get_missed_events(job_id, last_event_id)
    
    async def cache_progress_event(
        self,
        job_id: int,
        progress: ProgressMessageV2,
        ttl_seconds: int = 3600
    ) -> None:
        """
        Cache progress event for SSE resumption.
        
        Args:
            job_id: Job ID
            progress: Progress message
            ttl_seconds: Cache TTL in seconds
        """
        if not self._redis_client:
            await self.connect()
        
        cache_key = f"job:progress:cache:{job_id}"
        
        try:
            # Add to sorted set with event_id as score
            await self._redis_client.zadd(
                cache_key,
                {progress.model_dump_json(): progress.event_id}
            )
            
            # Set TTL on the cache
            await self._redis_client.expire(cache_key, ttl_seconds)
            
            # Trim to keep only last 1000 events
            await self._redis_client.zremrangebyrank(cache_key, 0, -1001)
            
        except Exception as e:
            logger.warning(f"Failed to cache progress event: {e}")
    
    async def get_active_subscriptions(self) -> Set[int]:
        """Get set of job IDs with active subscriptions."""
        return set(self._pubsub_clients.keys())
    
    async def get_recent_events_from_cache(
        self,
        job_id: int,
        count: int = 10
    ) -> List[str]:
        """
        Get recent events from cache.
        
        Args:
            job_id: Job ID
            count: Number of recent events to retrieve
            
        Returns:
            List of recent event JSON strings in reverse order (newest first)
        """
        if not self._redis_client:
            await self.connect()
        
        cache_key = f"job:progress:cache:{job_id}"
        events = []
        
        try:
            # Get most recent events (reverse order)
            events = await self._redis_client.zrevrange(
                cache_key,
                0,
                count - 1,
                withscores=False
            )
        except Exception as e:
            logger.warning(f"Failed to get recent events from cache: {e}")
        
        return events
    
    async def broadcast_system_message(self, message: Dict[str, Any]) -> int:
        """
        Broadcast system message to all job channels.
        
        Args:
            message: System message to broadcast
            
        Returns:
            Number of channels reached
        """
        if not self._redis_client:
            await self.connect()
        
        channels_reached = 0
        
        for job_id in self._pubsub_clients.keys():
            channel = self._get_channel_name(job_id)
            try:
                await self._redis_client.publish(
                    channel,
                    json.dumps({"system": True, **message})
                )
                channels_reached += 1
            except Exception as e:
                logger.warning(f"Failed to broadcast to {channel}: {e}")
        
        return channels_reached


# Global instance
redis_progress_pubsub = RedisProgressPubSub()


async def publish_worker_progress(
    job_id: int,
    event_type: str,
    phase: Optional[str] = None,
    progress_pct: Optional[int] = None,
    message: Optional[str] = None,
    milestone: bool = False,
    **kwargs
) -> bool:
    """
    Helper function for workers to publish progress.
    
    Args:
        job_id: Job ID
        event_type: Event type
        phase: Operation phase
        progress_pct: Progress percentage
        message: Progress message
        milestone: Whether this is a milestone
        **kwargs: Additional progress fields
        
    Returns:
        True if published successfully
    """
    progress = ProgressMessageV2(
        job_id=job_id,
        event_type=event_type,
        phase=phase,
        progress_pct=progress_pct,
        message=message,
        milestone=milestone,
        timestamp=datetime.now(timezone.utc),
        **kwargs
    )
    
    return await redis_progress_pubsub.publish_progress(job_id, progress)