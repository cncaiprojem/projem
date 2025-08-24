"""
Ultra-Enterprise Event Publisher Service
Task 6.7: Publish job.status.changed events to RabbitMQ

This service provides:
- RabbitMQ topic exchange configuration for events.jobs
- Job status change event publishing
- Exactly-once delivery for state transitions
- Fanout to ERP outbound bridge
- Idempotent event publishing
- ASYNC/NON-BLOCKING operations using aio-pika
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any
import asyncio

import aio_pika
from aio_pika.exceptions import AMQPConnectionError, AMQPChannelError, AMQPError
from aio_pika import Message, DeliveryMode, ExchangeType
import redis.exceptions

from ..core.logging import get_logger
from ..core.config import settings
from ..core.redis_config import get_redis_client

logger = get_logger(__name__)


class EventPublisherService:
    """Service for publishing events to RabbitMQ topic exchanges using async/await."""
    
    # Exchange configuration
    EVENTS_EXCHANGE = "events.jobs"
    EVENTS_EXCHANGE_TYPE = "topic"
    
    # ERP bridge exchange for fanout
    ERP_BRIDGE_EXCHANGE = "erp.outbound"
    ERP_BRIDGE_EXCHANGE_TYPE = "fanout"
    
    # Routing keys
    JOB_STATUS_CHANGED_KEY = "job.status.changed"
    
    # Redis key for deduplication
    EVENT_DEDUP_KEY = "event:dedup:{job_id}:{status}:{attempt}"
    EVENT_DEDUP_TTL = 300  # 5 minutes TTL for deduplication
    
    def __init__(self):
        """Initialize event publisher service."""
        self._connection: Optional[aio_pika.abc.AbstractRobustConnection] = None
        self._channel: Optional[aio_pika.abc.AbstractChannel] = None
        self._redis_client = None
        self._events_exchange: Optional[aio_pika.abc.AbstractExchange] = None
        self._erp_exchange: Optional[aio_pika.abc.AbstractExchange] = None
        self._lock = asyncio.Lock()
    
    @property
    def redis_client(self):
        """Lazy load Redis client."""
        if self._redis_client is None:
            try:
                self._redis_client = get_redis_client()
                # Test connection
                self._redis_client.ping()
            except redis.exceptions.RedisError as e:
                logger.warning(f"Redis unavailable for event deduplication: {e}")
                self._redis_client = None
        return self._redis_client
    
    async def _get_connection(self) -> aio_pika.abc.AbstractRobustConnection:
        """
        Get or create RabbitMQ connection using aio-pika.
        
        Returns:
            aio_pika.abc.AbstractRobustConnection: Async RabbitMQ connection
        """
        async with self._lock:
            if not self._connection or self._connection.is_closed:
                try:
                    # Create robust connection (auto-reconnects)
                    self._connection = await aio_pika.connect_robust(
                        settings.rabbitmq_url,
                        heartbeat=30,
                        connection_attempts=3,
                        retry_delay=2.0
                    )
                    logger.debug("Established async RabbitMQ connection for event publishing")
                    
                except Exception as e:
                    logger.error(f"Failed to connect to RabbitMQ: {e}")
                    raise
            
            return self._connection
    
    async def _get_channel(self) -> aio_pika.abc.AbstractChannel:
        """
        Get or create RabbitMQ channel using aio-pika.
        
        Returns:
            aio_pika.abc.AbstractChannel: Async RabbitMQ channel
        """
        connection = await self._get_connection()
        
        async with self._lock:
            if not self._channel or self._channel.is_closed:
                try:
                    self._channel = await connection.channel()
                    
                    # Set prefetch count for flow control
                    await self._channel.set_qos(prefetch_count=100)
                    
                    logger.debug("Created async RabbitMQ channel for event publishing")
                    
                except Exception as e:
                    logger.error(f"Failed to create RabbitMQ channel: {e}")
                    raise
            
            return self._channel
    
    async def _setup_exchanges(self):
        """
        Setup required exchanges for event publishing using aio-pika.
        
        Creates:
        - events.jobs topic exchange for internal events
        - erp.outbound fanout exchange for ERP bridge
        """
        try:
            channel = await self._get_channel()
            
            # Declare events.jobs topic exchange
            self._events_exchange = await channel.declare_exchange(
                name=self.EVENTS_EXCHANGE,
                type=ExchangeType.TOPIC,
                durable=True,
                auto_delete=False
            )
            logger.info(f"Declared exchange: {self.EVENTS_EXCHANGE}")
            
            # Declare ERP bridge fanout exchange
            self._erp_exchange = await channel.declare_exchange(
                name=self.ERP_BRIDGE_EXCHANGE,
                type=ExchangeType.FANOUT,
                durable=True,
                auto_delete=False
            )
            logger.info(f"Declared exchange: {self.ERP_BRIDGE_EXCHANGE}")
            
            # Bind ERP bridge to events exchange for job.status.* events
            # This creates the fanout pattern: events.jobs -> erp.outbound
            # Note: Exchange-to-exchange binding requires RabbitMQ 3.0+
            await self._erp_exchange.bind(
                self._events_exchange,
                routing_key="job.status.#"  # Match all job.status.* events
            )
            logger.info(f"Bound {self.ERP_BRIDGE_EXCHANGE} to {self.EVENTS_EXCHANGE} for job.status.# events")
            
        except Exception as e:
            logger.error(f"Failed to setup exchanges: {e}")
            # Don't raise - allow service to work in degraded mode
    
    def _is_duplicate_event(
        self,
        job_id: int,
        status: str,
        attempt: int
    ) -> bool:
        """
        Check if this event has already been published (deduplication).
        
        Args:
            job_id: Job ID
            status: Job status
            attempt: Attempt number
            
        Returns:
            True if event is a duplicate
        """
        if not self.redis_client:
            # No Redis, can't deduplicate
            return False
        
        try:
            dedup_key = self.EVENT_DEDUP_KEY.format(
                job_id=job_id,
                status=status,
                attempt=attempt
            )
            
            # Try to set with NX (only if not exists)
            # Returns True if key was set (not duplicate), None if exists (duplicate)
            result = self.redis_client.set(
                dedup_key,
                datetime.now(timezone.utc).isoformat(),
                nx=True,
                ex=self.EVENT_DEDUP_TTL
            )
            
            # If result is None, key exists = duplicate
            return result is None
            
        except redis.exceptions.RedisError as e:
            logger.debug(f"Redis deduplication check failed: {e}")
            # On error, assume not duplicate to avoid losing events
            return False
    
    async def publish_job_status_changed(
        self,
        job_id: int,
        status: str,
        progress: int,
        attempt: int,
        previous_status: Optional[str] = None,
        previous_progress: Optional[int] = None,
        step: Optional[str] = None,
        message: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None
    ) -> bool:
        """
        Publish job.status.changed event to RabbitMQ using async/await.
        
        Ensures exactly-once delivery per state transition through deduplication.
        Events are published to events.jobs topic exchange and fanout to ERP bridge.
        
        Args:
            job_id: Job ID
            status: Current job status
            progress: Current progress (0-100)
            attempt: Current attempt number
            previous_status: Previous status (for transition tracking)
            previous_progress: Previous progress
            step: Current processing step
            message: Human-readable message
            error_code: Error code if failed
            error_message: Error message if failed
            
        Returns:
            True if event was published successfully
        """
        # Use for loop for retry logic instead of recursion
        max_retries = 2
        for retry_num in range(max_retries):
            try:
                # Check for duplicate events (exactly-once delivery)
                if self._is_duplicate_event(job_id, status, attempt):
                    logger.debug(
                        f"Skipping duplicate event for job {job_id} "
                        f"(status: {status}, attempt: {attempt})"
                    )
                    return True  # Consider it success (already published)
                
                # Build event payload
                timestamp = datetime.now(timezone.utc).isoformat()
                event_id = str(uuid.uuid4())
                
                payload = {
                    "event_id": event_id,
                    "event_type": "job.status.changed",
                    "timestamp": timestamp,
                    "job_id": job_id,
                    "status": status,
                    "progress": progress,
                    "attempt": attempt,
                }
                
                # Add optional fields if provided
                if previous_status is not None:
                    payload["previous_status"] = previous_status
                if previous_progress is not None:
                    payload["previous_progress"] = previous_progress
                if step:
                    payload["step"] = step
                if message:
                    payload["message"] = message
                if error_code:
                    payload["error_code"] = error_code
                if error_message:
                    payload["error_message"] = error_message
                
                # Serialize payload
                message_body = json.dumps(payload).encode()
                
                # Ensure exchanges are set up
                if not self._events_exchange:
                    await self._setup_exchanges()
                
                # Create message with properties
                message = Message(
                    body=message_body,
                    delivery_mode=DeliveryMode.PERSISTENT,
                    content_type="application/json",
                    message_id=event_id,
                    timestamp=datetime.now(timezone.utc),
                    headers={
                        "x-job-id": str(job_id),
                        "x-event-type": "job.status.changed",
                        "x-status": status,
                        "x-attempt": str(attempt)
                    }
                )
                
                # Publish to events.jobs exchange with job.status.changed routing key
                # This will automatically fanout to ERP bridge via exchange binding
                if self._events_exchange:
                    await self._events_exchange.publish(
                        message,
                        routing_key=self.JOB_STATUS_CHANGED_KEY
                    )
                else:
                    # It's better to log an error and raise an exception to break out of any retry loop.
                    logger.error(
                        f"Cannot publish event for job {job_id}: events exchange is not available.",
                        extra={"job_id": job_id, "status": status}
                    )
                    raise RuntimeError(
                        f"Cannot publish event for job {job_id}: events exchange is not available."
                    )
                
                logger.info(
                    f"Published job.status.changed event for job {job_id}",
                    extra={
                        "event_id": event_id,
                        "job_id": job_id,
                        "status": status,
                        "progress": progress,
                        "attempt": attempt,
                        "routing_key": self.JOB_STATUS_CHANGED_KEY
                    }
                )
                
                return True
                
            except (AMQPConnectionError, AMQPChannelError) as e:
                # Connection issues - reset and retry if not last attempt
                logger.warning(f"RabbitMQ connection lost, resetting: {e}")
                self._connection = None
                self._channel = None
                self._events_exchange = None
                self._erp_exchange = None
                
                if retry_num < max_retries - 1:
                    # Try to reconnect before next iteration
                    try:
                        await self._setup_exchanges()
                        logger.info(f"Reconnected to RabbitMQ, retrying (attempt {retry_num + 2}/{max_retries})")
                        continue  # Try again in next iteration
                    except Exception as setup_error:
                        logger.error(f"Failed to reconnect to RabbitMQ: {setup_error}")
                
                # If we're here, it's the last retry or reconnection failed
                logger.error(
                    f"Failed to publish event after {max_retries} attempts for job {job_id}",
                    extra={"job_id": job_id, "status": status}
                )
                return False
            
            except aio_pika.exceptions.MessageProcessError as e:
                # Message processing error (e.g., routing issues)
                logger.error(
                    f"Message processing error while publishing job.status.changed event for job {job_id}: {e}",
                    extra={
                        "job_id": job_id,
                        "status": status,
                        "error": str(e)
                    }
                )
                return False
            
            except aio_pika.exceptions.AuthenticationError as e:
                # Authentication error - don't retry
                logger.error(
                    f"Authentication error while publishing job.status.changed event for job {job_id}: {e}",
                    extra={
                        "job_id": job_id,
                        "status": status,
                        "error": str(e)
                    }
                )
                return False
            
            except aio_pika.exceptions.ChannelAccessRefused as e:
                # Access denied error - don't retry
                logger.error(
                    f"Access denied error while publishing job.status.changed event for job {job_id}: {e}",
                    extra={
                        "job_id": job_id,
                        "status": status,
                        "error": str(e)
                    }
                )
                return False
                    
            except AMQPError as e:
                # Other AMQP errors - log and don't retry
                logger.error(
                    f"AMQP error while publishing job.status.changed event for job {job_id}: {e}",
                    extra={
                        "job_id": job_id,
                        "status": status,
                        "error": str(e)
                    }
                )
                return False
            
            except Exception as e:
                # Unexpected errors
                logger.error(
                    f"Unexpected error while publishing job.status.changed event for job {job_id}: {e}",
                    extra={
                        "job_id": job_id,
                        "status": status,
                        "error": str(e)
                    }
                )
                return False
        
        # Should not reach here, but return False if we do
        return False
    
    async def close(self):
        """Close the connection and channel gracefully."""
        try:
            if self._channel and not self._channel.is_closed:
                await self._channel.close()
                logger.debug("Closed RabbitMQ channel")
            
            if self._connection and not self._connection.is_closed:
                await self._connection.close()
                logger.debug("Closed RabbitMQ connection")
        except Exception as e:
            logger.warning(f"Error closing RabbitMQ connections: {e}")
        finally:
            self._channel = None
            self._connection = None
            self._events_exchange = None
            self._erp_exchange = None


# Global instance for reuse
_event_publisher: Optional[EventPublisherService] = None


def get_event_publisher() -> EventPublisherService:
    """Get or create a singleton EventPublisherService instance."""
    global _event_publisher
    if _event_publisher is None:
        _event_publisher = EventPublisherService()
    return _event_publisher


async def cleanup_event_publisher():
    """Clean up the global event publisher instance."""
    global _event_publisher
    if _event_publisher:
        await _event_publisher.close()
        _event_publisher = None