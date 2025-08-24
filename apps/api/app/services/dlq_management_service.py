"""
DLQ Management Service for Task 6.9

Ultra-enterprise service for managing Dead Letter Queues with:
- RabbitMQ Management API integration
- Message peeking without consumption
- Message replay with backoff and routing preservation
- Original headers and routing key preservation
- Thundering herd prevention
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import aiohttp
import aio_pika
from aio_pika import connect_robust, Message, DeliveryMode

from ..core.logging import get_logger
from ..core.queue_constants import (
    DLQ_SUFFIX,
    DLX_SUFFIX,
    QUEUE_DEFAULT,
    QUEUE_MODEL,
    QUEUE_CAM,
    QUEUE_SIM,
    QUEUE_REPORT,
    QUEUE_ERP
)
from ..config import settings

logger = get_logger(__name__)


class DLQManagementService:
    """
    Service for managing Dead Letter Queue operations.
    Integrates with RabbitMQ Management API for advanced operations.
    """
    
    # RabbitMQ Management API configuration
    RABBITMQ_MGMT_URL = settings.rabbitmq_management_url or "http://localhost:15672"
    RABBITMQ_USER = settings.rabbitmq_user or "freecad"
    RABBITMQ_PASS = settings.rabbitmq_pass or "freecad_dev_pass"
    RABBITMQ_VHOST = settings.rabbitmq_vhost or "/"
    
    # Known queue mappings for Task 6.1 topology
    QUEUE_MAPPINGS = {
        f"{QUEUE_DEFAULT}{DLQ_SUFFIX}": QUEUE_DEFAULT,
        f"{QUEUE_MODEL}{DLQ_SUFFIX}": QUEUE_MODEL,
        f"{QUEUE_CAM}{DLQ_SUFFIX}": QUEUE_CAM,
        f"{QUEUE_SIM}{DLQ_SUFFIX}": QUEUE_SIM,
        f"{QUEUE_REPORT}{DLQ_SUFFIX}": QUEUE_REPORT,
        f"{QUEUE_ERP}{DLQ_SUFFIX}": QUEUE_ERP,
    }
    
    # Known exchange routing for Task 6.1
    EXCHANGE_ROUTING = {
        QUEUE_DEFAULT: ("jobs", "jobs.ai"),
        QUEUE_MODEL: ("jobs", "jobs.model"),
        QUEUE_CAM: ("jobs", "jobs.cam"),
        QUEUE_SIM: ("jobs", "jobs.sim"),
        QUEUE_REPORT: ("jobs", "jobs.report"),
        QUEUE_ERP: ("jobs", "jobs.erp"),
    }
    
    def __init__(self):
        """Initialize DLQ Management Service."""
        self.auth = aiohttp.BasicAuth(self.RABBITMQ_USER, self.RABBITMQ_PASS)
        self._session: Optional[aiohttp.ClientSession] = None
        self._amqp_connection: Optional[aio_pika.RobustConnection] = None
        self._amqp_channel: Optional[aio_pika.RobustChannel] = None
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(auth=self.auth)
        return self._session
    
    async def __aenter__(self):
        """Context manager entry."""
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        """Context manager exit."""
        await self.close()
    
    async def close(self):
        """Close the aiohttp session and AMQP connection."""
        if self._session and not self._session.closed:
            await self._session.close()
        if self._amqp_channel:
            await self._amqp_channel.close()
        if self._amqp_connection:
            await self._amqp_connection.close()
    
    async def list_dlq_queues(self) -> List[Dict[str, Any]]:
        """
        List all DLQ queues with their message counts.
        
        Returns:
            List of DLQ queue information dictionaries
        """
        try:
            session = await self._get_session()
            
            # Get all queues from RabbitMQ Management API
            vhost_encoded = self.RABBITMQ_VHOST.replace("/", "%2F")
            url = f"{self.RABBITMQ_MGMT_URL}/api/queues/{vhost_encoded}"
            
            async with session.get(url) as response:
                if response.status != 200:
                    raise ValueError(f"Failed to get queues: {response.status}")
                
                all_queues = await response.json()
            
            # Filter for DLQ queues (ending with _dlq)
            dlq_queues = []
            for queue in all_queues:
                queue_name = queue.get("name", "")
                if queue_name.endswith(DLQ_SUFFIX):
                    # Extract relevant information
                    dlq_info = {
                        "name": queue_name,
                        "message_count": queue.get("messages", 0),
                        "messages_ready": queue.get("messages_ready", 0),
                        "messages_unacknowledged": queue.get("messages_unacknowledged", 0),
                        "consumers": queue.get("consumers", 0),
                        "idle_since": queue.get("idle_since"),
                        "memory": queue.get("memory", 0),
                        "state": queue.get("state", "unknown"),
                        "type": queue.get("type", "classic"),  # classic, quorum, or stream
                        "origin_queue": self.QUEUE_MAPPINGS.get(queue_name, "unknown")
                    }
                    dlq_queues.append(dlq_info)
            
            # Sort by message count descending
            dlq_queues.sort(key=lambda x: x["message_count"], reverse=True)
            
            logger.info(
                "Listed DLQ queues",
                queue_count=len(dlq_queues),
                total_messages=sum(q["message_count"] for q in dlq_queues)
            )
            
            return dlq_queues
            
        except Exception as e:
            logger.error("Failed to list DLQ queues", error=str(e))
            raise
    
    async def peek_messages(
        self,
        queue_name: str,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Peek messages in a DLQ without consuming them.
        
        Args:
            queue_name: Name of the DLQ queue
            limit: Number of messages to peek
            
        Returns:
            List of message preview dictionaries
        """
        if not queue_name.endswith(DLQ_SUFFIX):
            raise ValueError(f"Invalid DLQ queue name: {queue_name}")
        
        try:
            session = await self._get_session()
            
            # Use RabbitMQ Management API to get messages without consuming
            vhost_encoded = self.RABBITMQ_VHOST.replace("/", "%2F")
            url = f"{self.RABBITMQ_MGMT_URL}/api/queues/{vhost_encoded}/{queue_name}/get"
            
            # Request body for getting messages
            request_data = {
                "count": limit,
                "ackmode": "ack_requeue_true",  # Peek without consuming
                "encoding": "auto",
                "truncate": 50000  # Truncate large messages
            }
            
            async with session.post(url, json=request_data) as response:
                if response.status == 404:
                    raise ValueError(f"Queue not found: {queue_name}")
                elif response.status != 200:
                    raise ValueError(f"Failed to peek messages: {response.status}")
                
                messages_data = await response.json()
            
            # Parse and format messages
            messages = []
            for msg_data in messages_data:
                try:
                    # Extract message properties
                    properties = msg_data.get("properties", {})
                    headers = properties.get("headers", {})
                    
                    # Try to decode payload
                    payload_encoding = msg_data.get("payload_encoding", "string")
                    payload = msg_data.get("payload", "")
                    
                    if payload_encoding == "base64":
                        try:
                            payload = base64.b64decode(payload).decode("utf-8")
                            # Try to parse as JSON
                            payload = json.loads(payload)
                        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as e:
                            # Keep as string if not JSON
                            pass
                    
                    # Extract job_id if present
                    job_id = None
                    if isinstance(payload, dict):
                        job_id = payload.get("job_id")
                    if not job_id and headers:
                        job_id = headers.get("job_id")
                    
                    message_preview = {
                        "message_id": properties.get("message_id"),
                        "job_id": job_id,
                        "routing_key": msg_data.get("routing_key"),
                        "exchange": msg_data.get("exchange"),
                        "original_routing_key": headers.get("x-death", [{}])[0].get("routing-keys", [""])[0] if headers.get("x-death") else None,
                        "original_exchange": headers.get("x-death", [{}])[0].get("exchange") if headers.get("x-death") else None,
                        "death_count": len(headers.get("x-death", [])),
                        "first_death_reason": headers.get("x-death", [{}])[0].get("reason") if headers.get("x-death") else None,
                        "timestamp": properties.get("timestamp"),
                        "headers": headers,
                        "payload": payload,
                        "payload_bytes": msg_data.get("payload_bytes", 0),
                        "redelivered": msg_data.get("redelivered", False)
                    }
                    
                    messages.append(message_preview)
                    
                except Exception as e:
                    logger.warning(
                        "Failed to parse message",
                        queue_name=queue_name,
                        error=str(e)
                    )
                    continue
            
            logger.info(
                "Peeked DLQ messages",
                queue_name=queue_name,
                message_count=len(messages)
            )
            
            return messages
            
        except Exception as e:
            logger.error(
                "Failed to peek messages",
                queue_name=queue_name,
                error=str(e)
            )
            raise
    
    async def replay_messages(
        self,
        queue_name: str,
        max_messages: int = 10,
        backoff_ms: int = 100
    ) -> Dict[str, Any]:
        """
        Replay messages from DLQ back to their origin queues using aio-pika.
        
        Args:
            queue_name: Name of the DLQ queue
            max_messages: Maximum number of messages to replay
            backoff_ms: Backoff between messages in milliseconds
            
        Returns:
            Dictionary with replay results
        """
        if not queue_name.endswith(DLQ_SUFFIX):
            raise ValueError(f"Invalid DLQ queue name: {queue_name}")
        
        # Get origin queue name
        origin_queue = self.QUEUE_MAPPINGS.get(queue_name)
        if not origin_queue:
            raise ValueError(f"Unknown DLQ queue mapping: {queue_name}")
        
        # Get exchange and routing key for origin queue
        exchange_info = self.EXCHANGE_ROUTING.get(origin_queue)
        if not exchange_info:
            raise ValueError(f"Unknown exchange routing for queue: {origin_queue}")
        
        exchange_name, default_routing_key = exchange_info
        
        replayed_count = 0
        failed_count = 0
        details = []
        
        try:
            # Use aio-pika for async consuming and republishing
            conn_url = f"amqp://{self.RABBITMQ_USER}:{self.RABBITMQ_PASS}@{settings.rabbitmq_host}:{settings.rabbitmq_port}/{self.RABBITMQ_VHOST}"
            
            # Connect using aio-pika
            connection = await connect_robust(conn_url)
            
            try:
                # Create channel
                channel = await connection.channel()
                
                # Declare the DLQ queue
                dlq_queue = await channel.declare_queue(
                    queue_name,
                    durable=True,
                    passive=True  # Don't create, it should exist
                )
                
                # Declare the target exchange
                target_exchange = await channel.declare_exchange(
                    exchange_name,
                    passive=True  # Don't create, it should exist
                )
                
                # Process messages
                messages_processed = 0
                async with dlq_queue.iterator() as queue_iter:
                    async for message in queue_iter:
                        if messages_processed >= max_messages:
                            break
                        
                        try:
                            async with message.process(requeue=False):
                                # Extract original routing information
                                headers = message.headers or {}
                                x_death = headers.get("x-death", [])
                                
                                # Determine routing
                                if x_death and len(x_death) > 0:
                                    # Use original routing from x-death header
                                    death_info = x_death[0]
                                    replay_routing_key = death_info.get("routing-keys", [default_routing_key])[0]
                                else:
                                    # Use default routing
                                    replay_routing_key = default_routing_key
                                
                                # Remove x-death header to prevent re-death
                                clean_headers = {k: v for k, v in headers.items() if k != "x-death"}
                                
                                # Add replay metadata
                                clean_headers["x-dlq-replayed"] = True
                                clean_headers["x-dlq-replay-timestamp"] = datetime.now(timezone.utc).isoformat()
                                clean_headers["x-dlq-replay-queue"] = queue_name
                                
                                # Create new message for replay
                                new_message = Message(
                                    body=message.body,
                                    headers=clean_headers,
                                    content_type=message.content_type,
                                    content_encoding=message.content_encoding,
                                    priority=message.priority,
                                    correlation_id=message.correlation_id,
                                    reply_to=message.reply_to,
                                    expiration=message.expiration,
                                    message_id=message.message_id,
                                    timestamp=message.timestamp,
                                    type=message.type,
                                    user_id=message.user_id,
                                    app_id=message.app_id,
                                    delivery_mode=DeliveryMode.PERSISTENT
                                )
                                
                                # Publish to origin exchange/queue
                                await target_exchange.publish(
                                    new_message,
                                    routing_key=replay_routing_key
                                )
                                
                                # Message will be acknowledged when context exits
                                replayed_count += 1
                                messages_processed += 1
                                
                                details.append({
                                    "message_id": message.message_id,
                                    "replayed_to": f"{exchange_name}/{replay_routing_key}",
                                    "timestamp": datetime.now(timezone.utc).isoformat()
                                })
                                
                                # Apply backoff to prevent thundering herd
                                if backoff_ms > 0:
                                    await asyncio.sleep(backoff_ms / 1000.0)
                            
                        except Exception as e:
                            logger.error(
                                "Failed to replay message",
                                queue_name=queue_name,
                                error=str(e)
                            )
                            failed_count += 1
                            # Message will not be requeued (requeue=False) to prevent infinite loops
                
            finally:
                # Clean up connection
                await connection.close()
            
            logger.info(
                "Replayed DLQ messages",
                queue_name=queue_name,
                replayed_count=replayed_count,
                failed_count=failed_count
            )
            
            return {
                "replayed_count": replayed_count,
                "failed_count": failed_count,
                "details": details[:10]  # Limit details to first 10 for response size
            }
            
        except Exception as e:
            logger.error(
                "Failed to replay messages",
                queue_name=queue_name,
                error=str(e)
            )
            raise
    
    async def get_queue_depth(self, queue_name: str) -> int:
        """
        Get the current message count in a DLQ.
        
        Args:
            queue_name: Name of the DLQ queue
            
        Returns:
            Number of messages in the queue
        """
        try:
            session = await self._get_session()
            
            vhost_encoded = self.RABBITMQ_VHOST.replace("/", "%2F")
            url = f"{self.RABBITMQ_MGMT_URL}/api/queues/{vhost_encoded}/{queue_name}"
            
            async with session.get(url) as response:
                if response.status == 404:
                    return 0
                elif response.status != 200:
                    raise ValueError(f"Failed to get queue depth: {response.status}")
                
                queue_data = await response.json()
                return queue_data.get("messages", 0)
                
        except Exception as e:
            logger.error(
                "Failed to get queue depth",
                queue_name=queue_name,
                error=str(e)
            )
            return 0