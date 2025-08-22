"""
Celery 5.4 App Configuration - Task 6.1
RabbitMQ topology with per-queue dead-letter exchanges and DLQs.

This module provides the main Celery application configuration with:
- Jobs.direct exchange for primary queues
- Per-queue DLX and DLQ topology
- Quorum queues for primaries, classic lazy for DLQs
- Message size limits, publisher confirms, and proper routing
"""

from __future__ import annotations

import logging
from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from ..config import settings
from ..settings import app_settings as appset
from .queue_constants import (
    MAIN_QUEUES,
    DLX_SUFFIX,
    DLQ_SUFFIX,
    QUEUE_CONFIGS,
    DLQ_CONFIG,
    JOBS_EXCHANGE,
    JOBS_EXCHANGE_TYPE,
    ROUTING_KEYS,
    QUEUE_DEFAULT,
    QUEUE_MODEL,
    QUEUE_CAM,
    QUEUE_SIM,
    QUEUE_REPORT,
    QUEUE_ERP,
)

# Task 6.1: Celery 5.4 app initialization
celery_app = Celery(
    "freecad_tasks",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.assembly",
        "app.tasks.cam",
        "app.tasks.sim",
        "app.tasks.design",
        "app.tasks.cad",
        "app.tasks.cam_build",
        "app.tasks.reports",
        "app.tasks.m18_cam",
        "app.tasks.m18_sim",
        "app.tasks.m18_post",
        "app.tasks.maintenance",
        "app.tasks.monitoring",
        "app.tasks.license_notifications",
        "app.tasks.freecad",
    ],
)

# Auto-discover tasks from modules
celery_app.autodiscover_tasks(["app.tasks"])

# Task 6.1: Define exchanges
jobs_direct_exchange = Exchange(JOBS_EXCHANGE, type=JOBS_EXCHANGE_TYPE, durable=True)

# Create dead letter exchanges - one per primary queue
dlx_exchanges = {}
for queue_name in MAIN_QUEUES:
    dlx_name = f"{queue_name}{DLX_SUFFIX}"
    dlx_exchanges[queue_name] = Exchange(dlx_name, type="direct", durable=True)

# Task 6.1: Create primary queues with per-queue DLX configuration
# Create reverse mapping from queue name to routing key
ROUTING_KEYS_BY_QUEUE = {v: k for k, v in ROUTING_KEYS.items()}

primary_queues = []
for queue_name in MAIN_QUEUES:
    config = QUEUE_CONFIGS[queue_name]
    dlx_name = f"{queue_name}{DLX_SUFFIX}"
    
    # Priority mapping - Task 6.1 specs require specific priority handling
    priority_map = {
        "high": settings.queue_priority_high,
        "normal": settings.queue_priority_normal,
        "low": settings.queue_priority_low,
    }
    
    # Task 6.1: Quorum queue configuration for primaries
    queue_arguments = {
        # Dead letter configuration - each queue has its own DLX
        "x-dead-letter-exchange": dlx_name,
        "x-dead-letter-routing-key": "#",  # Catch all routing for DLX
        # Message and queue limits
        "x-message-ttl": config["ttl"],
        "x-max-length-bytes": config["max_message_bytes"],  # 10MB limit
        # Note: x-max-retries is not a valid RabbitMQ queue argument, retries handled by Celery
        # Priority handling
        "x-max-priority": 10,
        "x-priority": priority_map[config["priority"]],
        # Task 6.1: Quorum queue type for high availability
        "x-queue-type": config["queue_type"],
    }
    
    queue = Queue(
        queue_name,
        exchange=jobs_direct_exchange,
        routing_key=ROUTING_KEYS_BY_QUEUE[queue_name],
        durable=True,
        queue_arguments=queue_arguments,
    )
    primary_queues.append(queue)

# Task 6.1: Create dead letter queues - classic lazy mode
dlq_queues = []
for queue_name in MAIN_QUEUES:
    dlq_name = f"{queue_name}{DLQ_SUFFIX}"
    dlx_exchange = dlx_exchanges[queue_name]
    
    # Task 6.1: Classic lazy queue configuration for DLQs
    dlq_arguments = {
        "x-message-ttl": DLQ_CONFIG["ttl"],  # 24 hours
        "x-max-length": DLQ_CONFIG["max_length"],  # Max messages
        "x-queue-mode": DLQ_CONFIG["queue_mode"],  # Lazy mode
        "x-queue-type": "classic",  # Classic queue type for DLQs
    }
    
    dlq = Queue(
        dlq_name,
        exchange=dlx_exchange,
        routing_key="#",  # Catch all messages from DLX
        durable=True,
        queue_arguments=dlq_arguments,
    )
    dlq_queues.append(dlq)

# Task 6.1: Configure task queues using kombu Queue objects
celery_app.conf.task_queues = tuple(primary_queues + dlq_queues)

# Task 6.1: Basic QoS configuration - prefetch=8, acks_late=True
celery_app.conf.task_acks_late = True
celery_app.conf.task_acks_on_failure_or_timeout = True
celery_app.conf.task_reject_on_worker_lost = True
celery_app.conf.worker_prefetch_multiplier = 8  # Basic QoS prefetch=8

# Default queue configuration
celery_app.conf.task_default_queue = QUEUE_DEFAULT
celery_app.conf.task_default_exchange = JOBS_EXCHANGE
celery_app.conf.task_default_exchange_type = JOBS_EXCHANGE_TYPE
celery_app.conf.task_default_routing_key = "jobs.ai"

# Task 6.1: Task routing configuration - mapping job types to queues
celery_app.conf.task_routes = {
    # AI/General tasks -> default queue
    "app.tasks.maintenance.*": {
        "queue": QUEUE_DEFAULT,
        "routing_key": "jobs.ai",
        "priority": settings.queue_priority_normal,
    },
    "app.tasks.monitoring.*": {
        "queue": QUEUE_DEFAULT,
        "routing_key": "jobs.ai",
        "priority": settings.queue_priority_normal,
    },
    "app.tasks.license_notifications.*": {
        "queue": QUEUE_DEFAULT,
        "routing_key": "jobs.ai",
        "priority": settings.queue_priority_normal,
    },
    
    # Model generation tasks -> model queue
    "app.tasks.cad.*": {
        "queue": QUEUE_MODEL,
        "routing_key": "jobs.model",
        "priority": settings.queue_priority_high,
    },
    "app.tasks.assembly.*": {
        "queue": QUEUE_MODEL,
        "routing_key": "jobs.model",
        "priority": settings.queue_priority_high,
    },
    "app.tasks.design.*": {
        "queue": QUEUE_MODEL,
        "routing_key": "jobs.model",
        "priority": settings.queue_priority_high,
    },
    "app.tasks.freecad.*": {
        "queue": QUEUE_MODEL,
        "routing_key": "jobs.model",
        "priority": settings.queue_priority_high,
    },
    
    # CAM tasks -> cam queue
    "app.tasks.cam.*": {
        "queue": QUEUE_CAM,
        "routing_key": "jobs.cam",
        "priority": settings.queue_priority_high,
    },
    "app.tasks.cam_build.*": {
        "queue": QUEUE_CAM,
        "routing_key": "jobs.cam",
        "priority": settings.queue_priority_high,
    },
    "app.tasks.m18_cam.*": {
        "queue": QUEUE_CAM,
        "routing_key": "jobs.cam",
        "priority": settings.queue_priority_high,
    },
    
    # Simulation tasks -> sim queue
    "app.tasks.sim.*": {
        "queue": QUEUE_SIM,
        "routing_key": "jobs.sim",
        "priority": settings.queue_priority_high,
    },
    "app.tasks.m18_sim.*": {
        "queue": QUEUE_SIM,
        "routing_key": "jobs.sim",
        "priority": settings.queue_priority_high,
    },
    
    # Report generation tasks -> report queue
    "app.tasks.reports.*": {
        "queue": QUEUE_REPORT,
        "routing_key": "jobs.report",
        "priority": settings.queue_priority_low,
    },
    "app.tasks.m18_post.*": {
        "queue": QUEUE_REPORT,
        "routing_key": "jobs.report",
        "priority": settings.queue_priority_low,
    },
    
    # ERP integration tasks -> erp queue (placeholder for future ERP tasks)
    # "app.tasks.erp.*": {
    #     "queue": QUEUE_ERP,
    #     "routing_key": "jobs.erp", 
    #     "priority": settings.queue_priority_normal,
    # },
}

# Task 6.1: RabbitMQ broker configuration with publisher confirms
celery_app.conf.broker_connection_retry_on_startup = True
celery_app.conf.broker_connection_retry = True
celery_app.conf.broker_connection_max_retries = 10
celery_app.conf.broker_heartbeat = 30
celery_app.conf.broker_transport_options = {
    # Task 6.1: Publisher confirms and message persistence
    "publisher_confirms": True,  # Publisher confirms
    "max_retries": 3,
    "interval_start": 0,
    "interval_step": 0.2,
    "interval_max": 0.5,
    # Priority and routing configuration
    "priority_steps": list(range(10)),
    "sep": ":",
    "queue_order_strategy": "priority",
    "visibility_timeout": 43200,  # 12 hours
}

# Task annotations with rate limiting
celery_app.conf.task_annotations = {
    "app.tasks.assembly.*": {
        "rate_limit": appset.rate_limits.get("assembly", "6/m"),
        "max_message_size": 10485760,  # 10MB
    },
    "app.tasks.cam.*": {
        "rate_limit": appset.rate_limits.get("cam", "12/m"),
        "max_message_size": 10485760,
    },
    "app.tasks.sim.*": {
        "rate_limit": appset.rate_limits.get("sim", "4/m"),
        "max_message_size": 10485760,
    },
    "app.tasks.cad.*": {
        "rate_limit": appset.rate_limits.get("cad", "8/m"),
        "max_message_size": 10485760,
    },
}

# Retry configuration
celery_app.conf.task_default_retry_delay = 30
celery_app.conf.task_max_retries = 3
celery_app.conf.broker_pool_limit = settings.celery_broker_pool_limit

# Beat schedule configuration
celery_app.conf.beat_schedule = {
    # System health check - every 5 minutes
    "health-check": {
        "task": "app.tasks.maintenance.health_check",
        "schedule": 300.0,
        "options": {
            "queue": QUEUE_DEFAULT,
            "routing_key": "jobs.ai",
            "priority": settings.queue_priority_background
        }
    },
    # Temp file cleanup - daily
    "cleanup-temp-files": {
        "task": "app.tasks.maintenance.cleanup_temp_files",
        "schedule": 86400.0,
        "options": {
            "queue": QUEUE_DEFAULT,
            "routing_key": "jobs.ai",
            "priority": settings.queue_priority_background
        }
    },
    # Queue metrics collection - every minute
    "collect-queue-metrics": {
        "task": "app.tasks.monitoring.collect_queue_metrics",
        "schedule": 60.0,
        "options": {
            "queue": QUEUE_DEFAULT,
            "routing_key": "jobs.ai",
            "priority": settings.queue_priority_background
        }
    },
    # Dead Letter Queue cleanup - hourly
    "cleanup-dlq": {
        "task": "app.tasks.maintenance.cleanup_dead_letter_queue",
        "schedule": 3600.0,
        "options": {
            "queue": QUEUE_DEFAULT,
            "routing_key": "jobs.ai",
            "priority": settings.queue_priority_background
        }
    },
    # FreeCAD health check - every 10 minutes
    "freecad-health-check": {
        "task": "app.tasks.monitoring.freecad_health_check",
        "schedule": 600.0,
        "options": {
            "queue": QUEUE_MODEL,
            "routing_key": "jobs.model",
            "priority": settings.queue_priority_background
        }
    },
    # License notification scan - daily at 02:00 UTC
    "scan-licenses-for-notifications": {
        "task": "scan_licenses_for_notifications",
        "schedule": crontab(hour=2, minute=0),
        "options": {
            "queue": QUEUE_DEFAULT,
            "routing_key": "jobs.ai",
            "priority": settings.queue_priority_normal
        }
    },
}

celery_app.conf.timezone = "UTC"

# Serialization and content configuration
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_expires = 3600  # 1 hour

# Worker configuration
celery_app.conf.worker_disable_rate_limits = False
celery_app.conf.worker_enable_remote_control = True
celery_app.conf.worker_send_task_events = True
celery_app.conf.task_send_sent_event = True

# Set as default Celery app
celery_app.set_default()