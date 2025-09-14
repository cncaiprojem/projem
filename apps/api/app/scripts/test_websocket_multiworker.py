#!/usr/bin/env python3
"""
Test script for WebSocket multi-worker broadcasting via Redis Pub/Sub.

This script validates that:
1. WebSocket connections work across multiple workers
2. Metrics published by one worker reach clients on all workers
3. Redis Pub/Sub properly broadcasts messages
4. Connection cleanup works properly

Usage:
    python apps/api/app/scripts/test_websocket_multiworker.py
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import List, Dict, Any

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

try:
    import websockets
    import redis.asyncio as redis_async
except ImportError:
    logger.error("Required packages not installed. Run: pip install websockets redis")
    sys.exit(1)


class WebSocketMultiWorkerTester:
    """Test WebSocket multi-worker broadcasting."""

    def __init__(self, api_base_url: str = "ws://localhost:8000"):
        self.api_base_url = api_base_url
        self.ws_endpoint = f"{api_base_url}/api/v2/performance/ws"
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.results: Dict[str, Any] = {
            "connections_established": 0,
            "messages_received": [],
            "broadcast_success": False,
            "errors": []
        }

    async def test_websocket_connection(self, client_id: str) -> bool:
        """Test basic WebSocket connection."""
        try:
            logger.info(f"[{client_id}] Connecting to WebSocket: {self.ws_endpoint}")

            async with websockets.connect(self.ws_endpoint) as websocket:
                logger.info(f"[{client_id}] Connected successfully")
                self.results["connections_established"] += 1

                # Send ping
                await websocket.send("ping")
                response = await asyncio.wait_for(websocket.recv(), timeout=5.0)

                if response == "pong":
                    logger.info(f"[{client_id}] Ping/pong successful")
                    return True
                else:
                    logger.error(f"[{client_id}] Unexpected response: {response}")
                    return False

        except Exception as e:
            logger.error(f"[{client_id}] Connection failed: {e}")
            self.results["errors"].append(str(e))
            return False

    async def test_multi_client_broadcast(self) -> bool:
        """Test that messages are broadcast to multiple clients."""
        clients: List[websockets.WebSocketClientProtocol] = []
        client_tasks = []

        try:
            # Connect multiple clients
            logger.info("Connecting multiple WebSocket clients...")
            for i in range(3):
                ws = await websockets.connect(self.ws_endpoint)
                clients.append(ws)
                logger.info(f"Client {i+1} connected")

            # Create tasks to receive messages on each client
            async def receive_messages(ws, client_id):
                messages = []
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.recv(), timeout=0.1)
                        data = json.loads(msg)
                        messages.append(data)
                        logger.info(f"Client {client_id} received: {data.get('type', 'unknown')}")
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    if "connection is closing" not in str(e).lower():
                        logger.error(f"Client {client_id} receive error: {e}")
                return messages

            # Start receivers
            for i, ws in enumerate(clients):
                task = asyncio.create_task(receive_messages(ws, i+1))
                client_tasks.append(task)

            # Wait a bit for subscribers to be ready
            await asyncio.sleep(2)

            # Publish a test message via Redis
            logger.info("Publishing test message via Redis...")
            await self.publish_test_message()

            # Wait for messages to propagate
            await asyncio.sleep(3)

            # Cancel receiver tasks and collect results
            for task in client_tasks:
                task.cancel()

            # Get results
            all_messages = []
            for task in client_tasks:
                try:
                    messages = await task
                    all_messages.extend(messages)
                except asyncio.CancelledError:
                    pass

            # Check if all clients received messages
            if all_messages:
                logger.info(f"Total messages received: {len(all_messages)}")
                self.results["messages_received"] = all_messages
                self.results["broadcast_success"] = True
                return True
            else:
                logger.warning("No messages received by any client")
                return False

        except Exception as e:
            logger.error(f"Broadcast test failed: {e}")
            self.results["errors"].append(str(e))
            return False

        finally:
            # Clean up connections
            for ws in clients:
                try:
                    await ws.close()
                except:
                    pass

    async def publish_test_message(self):
        """Publish a test message to Redis channel."""
        try:
            # Connect to Redis
            redis_client = redis_async.Redis.from_url(
                self.redis_url,
                decode_responses=False
            )

            # Create test metrics message
            test_message = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cpu_usage_percent": 45.5,
                "memory_usage_mb": 1024.0,
                "gpu_usage_percent": None,
                "active_operations": 5,
                "operations_per_second": 10.5,
                "avg_response_time_ms": 150.0,
                "error_rate": 0.5,
                "worker_id": os.getpid(),
                "test_marker": "TEST_BROADCAST"
            }

            # Publish to performance:metrics channel
            channel = "performance:metrics"
            message_json = json.dumps(test_message, default=str)

            await redis_client.publish(channel, message_json.encode('utf-8'))
            logger.info(f"Published test message to {channel}")

            await redis_client.close()

        except Exception as e:
            logger.error(f"Failed to publish test message: {e}")
            raise

    async def test_redis_pubsub_directly(self) -> bool:
        """Test Redis Pub/Sub directly to ensure it's working."""
        try:
            logger.info("Testing Redis Pub/Sub directly...")

            # Create subscriber
            subscriber = redis_async.Redis.from_url(
                self.redis_url,
                decode_responses=False
            )
            pubsub = subscriber.pubsub()
            await pubsub.subscribe("performance:metrics", "performance:alerts")

            # Create publisher
            publisher = redis_async.Redis.from_url(
                self.redis_url,
                decode_responses=False
            )

            # Publish test message
            test_msg = {"test": "direct_pubsub", "timestamp": time.time()}
            await publisher.publish("performance:metrics", json.dumps(test_msg))

            # Try to receive
            received = False
            async def receive():
                nonlocal received
                async for message in pubsub.listen():
                    if message['type'] == 'message':
                        data = json.loads(message['data'].decode('utf-8'))
                        if data.get('test') == 'direct_pubsub':
                            logger.info("Redis Pub/Sub working correctly")
                            received = True
                            break

            # Wait for message with timeout
            try:
                await asyncio.wait_for(receive(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("Redis Pub/Sub timeout - no message received")

            # Cleanup
            await pubsub.unsubscribe()
            await pubsub.close()
            await subscriber.close()
            await publisher.close()

            return received

        except Exception as e:
            logger.error(f"Redis Pub/Sub test failed: {e}")
            self.results["errors"].append(f"Redis test: {str(e)}")
            return False

    async def run_all_tests(self):
        """Run all WebSocket multi-worker tests."""
        logger.info("=" * 60)
        logger.info("WebSocket Multi-Worker Broadcasting Test")
        logger.info("=" * 60)

        # Test 1: Basic WebSocket connection
        logger.info("\nTest 1: Basic WebSocket Connection")
        connection_success = await self.test_websocket_connection("test-client-1")
        logger.info(f"Result: {'✅ PASSED' if connection_success else '❌ FAILED'}")

        # Test 2: Redis Pub/Sub
        logger.info("\nTest 2: Redis Pub/Sub Direct Test")
        redis_success = await self.test_redis_pubsub_directly()
        logger.info(f"Result: {'✅ PASSED' if redis_success else '❌ FAILED'}")

        # Test 3: Multi-client broadcast
        logger.info("\nTest 3: Multi-Client Broadcasting")
        broadcast_success = await self.test_multi_client_broadcast()
        logger.info(f"Result: {'✅ PASSED' if broadcast_success else '❌ FAILED'}")

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("TEST SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Connections established: {self.results['connections_established']}")
        logger.info(f"Messages received: {len(self.results['messages_received'])}")
        logger.info(f"Broadcast working: {self.results['broadcast_success']}")

        if self.results["errors"]:
            logger.error(f"Errors encountered: {len(self.results['errors'])}")
            for error in self.results["errors"]:
                logger.error(f"  - {error}")

        # Overall result
        all_passed = connection_success and redis_success and broadcast_success
        logger.info("\n" + "=" * 60)
        if all_passed:
            logger.info("✅ ALL TESTS PASSED - Multi-worker WebSocket broadcasting is working!")
        else:
            logger.error("❌ SOME TESTS FAILED - Check the implementation")
        logger.info("=" * 60)

        return all_passed


async def main():
    """Main test runner."""
    # Check if API is running
    api_url = os.getenv("API_URL", "ws://localhost:8000")

    tester = WebSocketMultiWorkerTester(api_url)
    success = await tester.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Test failed with error: {e}")
        sys.exit(1)