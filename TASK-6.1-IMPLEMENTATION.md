# Task 6.1 Implementation: Celery and RabbitMQ Topology with DLX/DLQ

## Overview

Task 6.1 implements a comprehensive Celery 5.4 and RabbitMQ topology with per-queue dead-letter exchanges (DLX) and dead-letter queues (DLQ) for the Turkish CAD/CAM/CAD production platform. This implementation provides robust job orchestration with proper error handling and message persistence.

## Architecture

### Queue Topology

**Primary Queues (Quorum Type):**
- `default` - General AI tasks, maintenance, monitoring
- `model` - FreeCAD model generation, CAD operations  
- `cam` - CAM path generation, toolpath operations
- `sim` - Process simulation, analysis
- `report` - Report generation, post-processing
- `erp` - ERP integration tasks (future use)

**Dead Letter Topology:**
- Each primary queue has its own DLX: `<queue>.dlx`
- Each DLX routes to a DLQ: `<queue>_dlq`
- DLQs use classic lazy queues for efficient storage

### Exchange Configuration

**Main Exchange:** `jobs.direct` (direct type, durable)
- Routes messages to primary queues based on routing keys

**Dead Letter Exchanges:** Per-queue DLXs
- `default.dlx` → `default_dlq`  
- `model.dlx` → `model_dlq`
- `cam.dlx` → `cam_dlq`
- `sim.dlx` → `sim_dlq`
- `report.dlx` → `report_dlq`
- `erp.dlx` → `erp_dlq`

## Routing Key Mappings

| Routing Key | Target Queue | Purpose |
|-------------|--------------|---------|
| `jobs.ai` | `default` | AI tasks, general processing |
| `jobs.model` | `model` | 3D model generation |
| `jobs.cam` | `cam` | CAM operations |  
| `jobs.sim` | `sim` | Simulations |
| `jobs.report` | `report` | Reports |
| `jobs.erp` | `erp` | ERP integration |

## Implementation Files

### Core Configuration
- **`apps/api/app/core/celery_app.py`** - Main Celery 5.4 app configuration
- **`apps/api/app/core/queue_constants.py`** - Centralized queue definitions
- **`apps/api/app/tasks/worker.py`** - Updated worker configuration

### Infrastructure  
- **`infra/rabbitmq/init_queues.py`** - Python-based topology initialization
- **`scripts/init-task-6.1-topology.sh`** - Shell script wrapper
- **`infra/compose/docker-compose.dev.yml`** - Updated Docker Compose config

### Testing
- **`apps/api/app/scripts/test_dlx_dlq_topology.py`** - Comprehensive test suite

## Key Features

### 1. Celery 5.4 Configuration
- **Basic QoS:** prefetch=8, acks_late=True
- **Task queues:** Defined using kombu Queue objects  
- **Task routes:** Mapping task types to queues
- **Publisher confirms:** Enabled for message durability

### 2. Queue Types
- **Primary queues:** Quorum type for high availability
- **DLQs:** Classic lazy type for efficient dead letter storage
- **Message size limit:** 10MB enforced via policies

### 3. Error Handling
- **Per-queue DLX:** Each queue has dedicated error handling
- **Configurable TTL:** Different timeouts per queue type
- **Retry limits:** Configurable max retries before DLQ
- **Catch-all routing:** DLX uses `#` routing key

### 4. Worker Specialization
- **General workers:** Handle `default` and `report` queues
- **Priority workers:** Handle `model`, `cam`, `sim` queues  
- **Resource allocation:** Higher limits for intensive tasks

## Usage

### Initialize Topology
```bash
# Run the initialization script
./scripts/init-task-6.1-topology.sh

# Or run Python script directly
python infra/rabbitmq/init_queues.py
```

### Test Implementation
```bash
# Run comprehensive test suite
python apps/api/app/scripts/test_dlx_dlq_topology.py
```

### Start Workers
```bash
# Start all services with new topology
docker-compose -f infra/compose/docker-compose.dev.yml up -d

# Or start specific worker types
docker-compose -f infra/compose/docker-compose.dev.yml up workers workers-priority
```

### Monitor Queues
- **Management UI:** http://localhost:15672
- **Username:** freecad
- **Password:** freecad_dev_pass

## Queue Configuration Details

### Default Queue
- **TTL:** 30 minutes
- **Max retries:** 3
- **Priority:** Normal (5)
- **Use case:** AI tasks, maintenance, monitoring

### Model Queue  
- **TTL:** 1 hour
- **Max retries:** 3
- **Priority:** High (7)
- **Use case:** FreeCAD operations, 3D model generation

### CAM Queue
- **TTL:** 45 minutes
- **Max retries:** 3  
- **Priority:** High (7)
- **Use case:** CAM path generation, toolpath operations

### Sim Queue
- **TTL:** 1 hour
- **Max retries:** 3
- **Priority:** High (7) 
- **Use case:** Process simulation, FEA analysis

### Report Queue
- **TTL:** 15 minutes
- **Max retries:** 2
- **Priority:** Low (3)
- **Use case:** Report generation, post-processing

### ERP Queue
- **TTL:** 30 minutes  
- **Max retries:** 2
- **Priority:** Normal (5)
- **Use case:** Future ERP integration tasks

## Dead Letter Queue Configuration

All DLQs share common configuration:
- **TTL:** 24 hours (messages expire after 1 day)
- **Max length:** 10,000 messages
- **Queue mode:** Lazy (for storage efficiency)
- **Queue type:** Classic (not quorum)

## Task Routing Examples

### Sending Tasks to Specific Queues

```python
# Model generation task
result = celery_app.send_task(
    "app.tasks.cad.generate_model",
    args=[model_params],
    queue="model",
    routing_key="jobs.model"
)

# CAM generation task  
result = celery_app.send_task(
    "app.tasks.cam.generate_toolpath", 
    args=[cam_params],
    queue="cam",
    routing_key="jobs.cam"
)

# Simulation task
result = celery_app.send_task(
    "app.tasks.sim.run_simulation",
    args=[sim_params], 
    queue="sim",
    routing_key="jobs.sim"
)
```

### Task Decorator Usage

```python
from celery import shared_task

@shared_task(bind=True, name="model_generation", queue="model")
def generate_model_task(self, params):
    # Will automatically route to model queue
    pass

@shared_task(bind=True, name="cam_generation", queue="cam")  
def generate_cam_task(self, params):
    # Will automatically route to cam queue
    pass
```

## Monitoring and Debugging

### Check Queue Status
```bash
# Using RabbitMQ management API
curl -u freecad:freecad http://localhost:15672/api/queues

# Using Celery inspect
celery -A app.tasks.worker inspect active_queues
```

### Monitor Dead Letter Queues
```bash
# Check DLQ message counts
curl -u freecad:freecad http://localhost:15672/api/queues | jq '.[] | select(.name | endswith("_dlq")) | {name: .name, messages: .messages}'
```

### View Task Routes
```bash
# Check configured routes
celery -A app.tasks.worker inspect registered
```

## Acceptance Criteria Validation

✅ **Publishing messages with each routing key delivers to correct primary queue**
- Routing key `jobs.model` → `model` queue
- Routing key `jobs.cam` → `cam` queue  
- Routing key `jobs.sim` → `sim` queue
- Routing key `jobs.report` → `report` queue
- Routing key `jobs.erp` → `erp` queue
- Routing key `jobs.ai` → `default` queue

✅ **Rejecting with requeue=False routes to corresponding DLQ**
- Failed `model` tasks → `model_dlq`
- Failed `cam` tasks → `cam_dlq`
- Failed `sim` tasks → `sim_dlq` 
- Failed `report` tasks → `report_dlq`
- Failed `erp` tasks → `erp_dlq`
- Failed `default` tasks → `default_dlq`

✅ **Celery workers consume from their expected queues**
- General workers consume `default`, `report`
- Priority workers consume `model`, `cam`, `sim`
- ERP workers (future) will consume `erp`

## Legacy Compatibility

The implementation includes backward compatibility during migration:

```python
# Legacy queue mapping
LEGACY_QUEUE_MAPPING = {
    "freecad": "model",    # FreeCAD tasks → model queue
    "cpu": "default",      # CPU tasks → default queue  
    "postproc": "report",  # Post-processing → report queue
}
```

## Next Steps

With Task 6.1 completed, the foundation is ready for:
- **Task 6.2:** Retry strategy, backoff with jitter, and error taxonomy
- **Task 6.3:** Job idempotency with database state tracking
- **Task 6.4:** Audit chain for complete job lifecycle tracking

## Troubleshooting

### Common Issues

1. **Queues not created**
   - Run initialization script: `./scripts/init-task-6.1-topology.sh`
   - Check RabbitMQ is running and accessible

2. **Messages not routing correctly**
   - Verify routing keys match ROUTING_KEYS
   - Check exchange bindings in management UI

3. **Workers not consuming**
   - Ensure workers are started with correct queue names  
   - Check worker logs for connection issues

4. **DLQ not receiving failed messages**
   - Verify DLX configuration on primary queues
   - Check message TTL and retry limits

### Log Locations
- **API logs:** `infra/compose/data/api-logs/`
- **Worker logs:** `infra/compose/data/worker-logs/`
- **Priority worker logs:** `infra/compose/data/worker-priority-logs/`

---

**Implementation completed:** Task 6.1 ✅  
**Next task:** Task 6.2 - Retry strategy, backoff with jitter, and error taxonomy