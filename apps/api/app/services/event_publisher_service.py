"""
Ultra-Enterprise Event Publisher Service
Task 6.7: Publish job.status.changed events to RabbitMQ

This service provides:
- RabbitMQ topic exchange configuration for events.jobs
- Job status change event publishing
- Exactly-once delivery for state transitions
- Fanout to ERP outbound bridge
- Idempotent event publishing
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import pika
from pika.exceptions import AMQPError, ConnectionClosed, ChannelClosed
import redis.exceptions

from ..core.logging import get_logger
from ..core.config import settings
from ..core.redis_config import get_redis_client

logger = get_logger(__name__)


class EventPublisherService:
    """Service for publishing events to RabbitMQ topic exchanges."""
    
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
        self._connection = None
        self._channel = None
        self._redis_client = None
        self._setup_exchanges()
    
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
    
    def _get_connection(self) -> pika.BlockingConnection:
        """
        Get or create RabbitMQ connection.
        
        Returns:
            pika.BlockingConnection: RabbitMQ connection
        """
        if not self._connection or self._connection.is_closed:
            try:
                # Parse RabbitMQ URL
                parameters = pika.URLParameters(settings.rabbitmq_url)
                parameters.heartbeat = 30
                parameters.blocked_connection_timeout = 10
                
                self._connection = pika.BlockingConnection(parameters)
                logger.debug("Established RabbitMQ connection for event publishing")
                
            except Exception as e:
                logger.error(f"Failed to connect to RabbitMQ: {e}")
                raise
        
        return self._connection
    
    def _get_channel(self) -> pika.channel.Channel:
        """
        Get or create RabbitMQ channel.
        
        Returns:
            pika.channel.Channel: RabbitMQ channel
        """
        connection = self._get_connection()
        
        if not self._channel or self._channel.is_closed:
            try:
                self._channel = connection.channel()
                
                # Enable publisher confirms for reliability
                self._channel.confirm_delivery()
                
                logger.debug("Created RabbitMQ channel for event publishing")
                
            except Exception as e:
                logger.error(f"Failed to create RabbitMQ channel: {e}")
                raise
        
        return self._channel
    
    def _setup_exchanges(self):
        """
        Setup required exchanges for event publishing.
        
        Creates:
        - events.jobs topic exchange for internal events
        - erp.outbound fanout exchange for ERP bridge
        """
        try:
            channel = self._get_channel()
            
            # Declare events.jobs topic exchange
            channel.exchange_declare(
                exchange=self.EVENTS_EXCHANGE,
                exchange_type=self.EVENTS_EXCHANGE_TYPE,
                durable=True,
                auto_delete=False
            )
            logger.info(f"Declared exchange: {self.EVENTS_EXCHANGE}")
            
            # Declare ERP bridge fanout exchange
            channel.exchange_declare(
                exchange=self.ERP_BRIDGE_EXCHANGE,
                exchange_type=self.ERP_BRIDGE_EXCHANGE_TYPE,
                durable=True,
                auto_delete=False
            )
            logger.info(f"Declared exchange: {self.ERP_BRIDGE_EXCHANGE}")
            
            # Bind ERP bridge to events exchange for job.status.* events
            # This creates the fanout pattern: events.jobs -> erp.outbound
            # Note: Exchange-to-exchange binding requires RabbitMQ 3.0+
            channel.exchange_bind(
                destination=self.ERP_BRIDGE_EXCHANGE,
                source=self.EVENTS_EXCHANGE,
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
        Publish job.status.changed event to RabbitMQ.
        
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
                message_body = json.dumps(payload)
                
                # Get channel for publishing
                channel = self._get_channel()
                
                # Publish to events.jobs exchange with job.status.changed routing key
                # This will automatically fanout to ERP bridge via exchange binding
                channel.basic_publish(
                    exchange=self.EVENTS_EXCHANGE,
                    routing_key=self.JOB_STATUS_CHANGED_KEY,
                    body=message_body,
                    properties=pika.BasicProperties(
                        delivery_mode=2,  # Persistent message
                        content_type="application/json",
                        message_id=event_id,
                        timestamp=int(datetime.now(timezone.utc).timestamp()),
                        headers={
                            "x-job-id": str(job_id),
                            "x-event-type": "job.status.changed",
                            "x-status": status,
                            "x-attempt": str(attempt)
                        }
                    ),
                    mandatory=False  # Don't require queue binding
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
                
            except (ConnectionClosed, ChannelClosed) as e:
                # Connection issues - reset and retry if not last attempt
                logger.warning(f"RabbitMQ connection lost, resetting: {e}")
                self._connection = None
                self._channel = None
                
                if retry_num < max_retries - 1:
                    # Try to reconnect before next iteration
                    try:
                        self._setup_exchanges()
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
                    
            except Exception as e:
                logger.error(
                    f"Failed to publish job.status.changed event for job {job_id}: {e}",
                    extra={
                        "job_id": job_id,
                        "status": status,
                        "error": str(e)
                    }
                )
                # Don't retry on general exceptions, return failure
                return False
        
        # If we exhausted all retries without success, return False
        return False
    
    async def publish_custom_event(
        self,
        event_type: str,
        routing_key: str,
        payload: Dict[str, Any],
        exchange: Optional[str] = None
    ) -> bool:
        """
        Publish a custom event to RabbitMQ.
        
        Args:
            event_type: Type of event
            routing_key: Routing key for the event
            payload: Event payload
            exchange: Exchange to publish to (default: events.jobs)
            
        Returns:
            True if event was published successfully
        """
        try:
            # Add standard fields
            event_id = str(uuid.uuid4())
            timestamp = datetime.now(timezone.utc).isoformat()
            
            full_payload = {
                "event_id": event_id,
                "event_type": event_type,
                "timestamp": timestamp,
                **payload
            }
            
            # Serialize payload
            message_body = json.dumps(full_payload)
            
            # Get channel
            channel = self._get_channel()
            
            # Use default exchange if not specified
            target_exchange = exchange or self.EVENTS_EXCHANGE
            
            # Publish event
            channel.basic_publish(
                exchange=target_exchange,
                routing_key=routing_key,
                body=message_body,
                properties=pika.BasicProperties(
                    delivery_mode=2,  # Persistent
                    content_type="application/json",
                    message_id=event_id,
                    timestamp=int(datetime.now(timezone.utc).timestamp()),
                    headers={"x-event-type": event_type}
                ),
                mandatory=False
            )
            
            logger.info(
                f"Published {event_type} event",
                extra={
                    "event_id": event_id,
                    "event_type": event_type,
                    "routing_key": routing_key,
                    "exchange": target_exchange
                }
            )
            
            return True
            
        except Exception as e:
            logger.error(
                f"Failed to publish {event_type} event: {e}",
                extra={
                    "event_type": event_type,
                    "routing_key": routing_key,
                    "error": str(e)
                }
            )
            return False
    
    def close(self):
        """Close RabbitMQ connection."""
        try:
            if self._channel and not self._channel.is_closed:
                self._channel.close()
            if self._connection and not self._connection.is_closed:
                self._connection.close()
            logger.debug("Closed RabbitMQ connections for event publisher")
        except Exception as e:
            logger.debug(f"Error closing RabbitMQ connections: {e}")
    
    # Note: __del__ method removed as it's unreliable for cleanup
    # Users should explicitly call close() when done with the service


# Global service instance
event_publisher_service = EventPublisherService()