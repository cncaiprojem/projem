# WebSocket Multi-Worker Architecture with Redis Pub/Sub

## Problem Statement

The original `ConnectionManager` implementation stored WebSocket connections locally in each worker process. This caused:
- WebSocket connections were worker-specific
- Metrics/alerts only reached clients connected to the same worker
- Inconsistent real-time monitoring across workers
- Violated the "complete multi-worker state management" goal of PR #613

## Solution Architecture

### Overview

We implemented Redis Pub/Sub for WebSocket broadcasting across all workers:

```
Worker 1: Generates metric → Publishes to Redis channel
                                    ↓
Redis Pub/Sub Channels: "performance:metrics", "performance:alerts"
                                    ↓
Worker 1, 2, 3: Subscribe → Forward to their local WebSocket clients
```

### Key Components

#### 1. ConnectionManager Changes

The `ConnectionManager` class now:
- Maintains local WebSocket connections per worker
- Publishes metrics/alerts to Redis channels instead of direct sending
- Subscribes to Redis channels and forwards messages to local clients
- Uses connection pooling for efficient Redis operations

#### 2. Redis Channels

Two dedicated channels for broadcasting:
- `performance:metrics` - Real-time performance metrics
- `performance:alerts` - Performance alerts and warnings

#### 3. Message Flow

1. **Metric Generation**: Worker generates performance metric
2. **Redis Publishing**: Metric published to Redis channel
3. **Broadcasting**: All workers receive via subscription
4. **Client Delivery**: Each worker forwards to its local WebSocket clients

### Implementation Details

#### Publisher Pool
- Lazy-initialized async Redis connection pool
- Reused for all publish operations
- Max 10 connections per worker

#### Subscriber Connection
- Dedicated Redis connection for Pub/Sub (Redis requirement)
- Runs async listener loop while clients connected
- Auto-reconnect on errors with 5-second delay

#### Backward Compatibility
- `send_metrics()` and `send_alert()` methods retained
- Now internally call `publish_metrics()` and `publish_alert()`
- No changes needed to existing code using these methods

### Benefits

1. **True Multi-Worker Support**: All clients receive updates regardless of connected worker
2. **Scalability**: Can scale to any number of workers
3. **Reliability**: Redis handles message distribution reliably
4. **Performance**: Connection pooling and async operations
5. **Maintainability**: Clean separation of concerns

### Testing

Run the test script to validate multi-worker broadcasting:

```bash
python apps/api/app/scripts/test_websocket_multiworker.py
```

The test validates:
- Basic WebSocket connectivity
- Redis Pub/Sub functionality
- Multi-client message broadcasting
- Proper cleanup on disconnection

### Configuration

No additional configuration required. Uses existing Redis connection from `state_manager`.

### Monitoring

Worker-specific logging includes:
- Worker PID in log messages
- Connection counts per worker
- Redis Pub/Sub subscription status
- Error handling with reconnection

### Error Handling

- Automatic reconnection on Redis errors
- Graceful handling of disconnected WebSocket clients
- Proper cleanup of resources on shutdown
- Detailed error logging for debugging

## Migration Notes

This is a drop-in replacement that maintains backward compatibility. No changes required to:
- Existing WebSocket client code
- Message formats
- API endpoints
- Configuration

## Performance Considerations

- Redis Pub/Sub adds minimal latency (~1-5ms)
- Connection pooling reduces overhead
- Async operations prevent blocking
- Efficient message serialization with JSON

## Security

- Uses existing Redis authentication
- No sensitive data in channel names
- Worker ID included for debugging (non-sensitive)
- Maintains all existing security measures