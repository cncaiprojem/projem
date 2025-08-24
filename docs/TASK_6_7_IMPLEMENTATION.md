# Task 6.7: Worker Progress Update Conventions and Status Change Events

## Overview

Task 6.7 implements a comprehensive worker progress reporting system with automatic event publishing for job status changes. This enables real-time progress tracking, throttled database updates, and integration with external systems via RabbitMQ events.

## Implementation Components

### 1. Worker Progress Service (`app/services/worker_progress_service.py`)

The core service that manages progress updates with:
- **Throttling**: Updates limited to max once per 2s per job to reduce DB load
- **Monotonic Validation**: Progress can only increase, never decrease
- **Coalescing**: Rapid updates within throttle window are coalesced
- **Atomic Updates**: Database operations use row-level locking
- **Event Triggering**: Automatically publishes events on status transitions

Key methods:
- `update_progress()`: Update job progress with throttling
- `update_job_status()`: Explicit status transitions
- `get_progress()`: Retrieve current progress information

### 2. Event Publisher Service (`app/services/event_publisher_service.py`)

Manages RabbitMQ event publishing with:
- **Topic Exchange**: `events.jobs` for internal event routing
- **Fanout Exchange**: `erp.outbound` for ERP integration
- **Exchange Binding**: Automatic routing of `job.status.*` events to ERP
- **Deduplication**: Exactly-once delivery per state transition
- **Connection Pooling**: Efficient RabbitMQ connection management

Event payload structure:
```json
{
  "event_id": "uuid",
  "event_type": "job.status.changed",
  "timestamp": "2024-01-20T10:30:00Z",
  "job_id": 123,
  "status": "running",
  "progress": 50,
  "attempt": 1,
  "previous_status": "queued",
  "previous_progress": 0,
  "step": "processing",
  "message": "Processing data"
}
```

### 3. Worker Helper Functions (`app/tasks/worker_helpers.py`)

Simple API for workers to report progress:

```python
from app.tasks.worker_helpers import progress, start_job, complete_job, fail_job

# Report progress (throttled)
progress(db, job_id, 50, "processing", "Halfway done", {"items": 100})

# Start a job
start_job(db, job_id, "Beginning processing")

# Complete a job
complete_job(db, job_id, {"output": "result.stl"}, "Success!")

# Fail a job
fail_job(db, job_id, "ERR_001", "Something went wrong", progress_percent=75)
```

**Performance Note**: The `progress()` function implements intelligent throttling to prevent excessive database updates during rapid progress reporting. While this optimizes database performance, be aware that very frequent progress updates (e.g., in tight loops) may be coalesced, and only the most recent update within the throttling window will be persisted. For optimal performance, call `progress()` at meaningful intervals (e.g., every 5-10% of progress) rather than on every iteration of high-frequency loops.

### 4. Updated CAD Worker (`app/tasks/cad.py`)

Example integration showing progress reporting throughout task execution:
- Reports progress at each major step
- Uses throttled updates for efficiency
- Handles cancellation checks
- Reports completion/failure with final state

## Features

### Progress Throttling

Updates are throttled to reduce database load:
- Maximum one update per 2 seconds per job
- Coalescing of rapid updates within throttle window
- Force flag available for critical updates

### Monotonic Progress

Progress validation ensures:
- Progress never decreases
- Values clamped to 0-100 range
- Invalid updates rejected with clear error

### Status Transitions

Automatic status changes based on progress:
- 0% + PENDING → QUEUED
- >0% + PENDING/QUEUED → RUNNING
- Explicit completion required for COMPLETED status

### Event Publishing

Events published for:
- All status transitions
- Milestone progress (0, 25, 50, 75, 100%)
- Significant progress changes (≥10%)

### Integration Points

- **Redis**: Throttling, coalescing, deduplication
- **RabbitMQ**: Event publishing to topic/fanout exchanges
- **Database**: Atomic updates with row locking
- **Workers**: Simple helper functions for easy adoption

## Testing

### Unit Tests (`tests/test_worker_progress.py`)

Comprehensive test coverage including:
- Monotonic progress validation
- Throttling mechanism
- Event publishing
- Worker helper functions
- Integration scenarios

### Test Script (`app/scripts/test_task_6_7.py`)

Interactive test demonstrating:
1. Progress updates with throttling
2. Status transitions
3. Event publishing
4. Worker helpers
5. Complete job lifecycle

### Exchange Setup (`app/scripts/init_event_exchanges.py`)

Script to initialize RabbitMQ exchanges:
```bash
python apps/api/app/scripts/init_event_exchanges.py
```

## Configuration

### Environment Variables

```bash
# Redis (for throttling/caching)
REDIS_URL=redis://localhost:6379/0

# RabbitMQ (for event publishing)
RABBITMQ_URL=amqp://freecad:freecad_dev_pass@localhost:5672/
```

### RabbitMQ Topology

```
jobs.direct (existing)
    → Queue routing for jobs

events.jobs (new - topic exchange)
    → job.status.changed events
    → Routes to interested consumers

erp.outbound (new - fanout exchange)
    → Receives all job.status.* from events.jobs
    → Fans out to ERP integration queues
```

## Usage Example

```python
from celery import shared_task
from app.tasks.worker_helpers import progress, start_job, complete_job, fail_job

@shared_task(bind=True)
def process_model_task(self, job_id: int):
    db = SessionLocal()
    try:
        # Start job
        start_job(db, job_id, "Initializing model processing")
        
        # Report progress throughout
        progress(db, job_id, 10, "setup", "Setting up environment")
        
        # Process model...
        for i in range(20, 90, 10):
            progress(db, job_id, i, "processing", f"Processing step {i}%")
            # Do work...
        
        # Complete job
        output = {"model": "output.stl", "size": 1024}
        complete_job(db, job_id, output, "Model processing complete")
        
    except Exception as e:
        fail_job(db, job_id, "MODEL_ERROR", str(e))
        raise
    finally:
        db.close()
```

## Acceptance Criteria ✓

1. **Progress Monotonic**: ✓ Progress advances monotonically (never decreases)
2. **Visibility via GET**: ✓ Progress visible through GET /jobs/{id} endpoint
3. **Event Publishing**: ✓ Events published exactly once per transition
4. **ERP Bridge**: ✓ Events fanout to erp.outbound exchange
5. **Throttling**: ✓ Updates throttled to max once per 2s per job
6. **Coalescing**: ✓ Rapid updates coalesced within throttle window

## API Endpoints

### GET /api/v1/jobs/{job_id}

Returns job details with progress information:
```json
{
  "id": 123,
  "type": "model",
  "status": "running",
  "progress": {
    "percent": 50,
    "step": "processing",
    "message": "Processing frame 50 of 100",
    "updated_at": "2024-01-20T10:30:00Z"
  },
  "attempts": 1,
  "cancel_requested": false,
  "artefacts": [],
  "queue_position": null
}
```

## Migration Notes

- No database schema changes required (uses existing fields)
- Backward compatible with existing workers
- Gradual adoption possible (workers can migrate incrementally)
- Existing jobs continue to work without progress reporting

## Performance Considerations

- Redis caching reduces database load
- Throttling prevents update storms
- Coalescing reduces total writes
- Event deduplication prevents duplicate messages
- Atomic operations ensure consistency

## Security

- All updates require valid job ID
- Progress validation prevents invalid data
- Event payloads sanitized
- Rate limiting on API endpoints
- Authorization checks on job access