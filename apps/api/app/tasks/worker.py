from __future__ import annotations

from celery import Celery
from kombu import Exchange, Queue

from ..config import settings
from ..core.queue_constants import (
    DLQ_CONFIG,
    DLQ_PREFIX,
    MAIN_QUEUES,
    QUEUE_CONFIGS,
)
from ..settings import app_settings as appset

celery_app = Celery(
    "freecad_tasks",
    broker=settings.rabbitmq_url,
    backend=settings.redis_url,  # Keep Redis as result backend
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
    ],
)

# Ek güvence: paket altındaki tüm task modüllerini keşfet
try:  # pragma: no cover
    celery_app.autodiscover_tasks(["app.tasks"])  # type: ignore[arg-type]
except Exception:
    pass

# RabbitMQ Exchange ve Dead Letter Exchange konfigürasyonu
default_exchange = Exchange("celery", type="direct", durable=True)
dlx_exchange = Exchange("dlx", type="direct", durable=True)

# Dead Letter Queue konfigürasyonu - dinamik olarak oluştur
dlq_queues = []
for queue_name in MAIN_QUEUES:
    dlq = Queue(
        f"{DLQ_PREFIX}{queue_name}",
        exchange=dlx_exchange,
        routing_key=queue_name,
        durable=True,
        queue_arguments={
            "x-message-ttl": DLQ_CONFIG["ttl"],
            "x-max-length": DLQ_CONFIG["max_length"],
        }
    )
    dlq_queues.append(dlq)

# Main queues konfigürasyonu - dinamik olarak oluştur
main_queues = []
for queue_name in MAIN_QUEUES:
    config = QUEUE_CONFIGS[queue_name]

    # Priority mapping
    priority_map = {
        "high": settings.queue_priority_high,
        "normal": settings.queue_priority_normal,
        "low": settings.queue_priority_low,
    }

    queue = Queue(
        queue_name,
        exchange=default_exchange,
        routing_key=queue_name,
        durable=True,
        queue_arguments={
            "x-dead-letter-exchange": "dlx",
            "x-dead-letter-routing-key": queue_name,
            "x-message-ttl": config["ttl"],
            "x-max-retries": config["max_retries"],
            "x-priority": priority_map[config["priority"]],
        }
    )
    main_queues.append(queue)

# RabbitMQ Queue konfigürasyonu (Dead Letter Exchange ile)
celery_app.conf.task_queues = tuple(main_queues + dlq_queues)

# Celery konfigürasyonu
celery_app.conf.task_default_queue = "cpu"
celery_app.conf.task_acks_late = settings.celery_task_acks_late
celery_app.conf.task_acks_on_failure_or_timeout = True
celery_app.conf.task_reject_on_worker_lost = settings.celery_task_reject_on_worker_lost
celery_app.conf.task_default_retry_delay = 30
celery_app.conf.task_max_retries = 3
celery_app.conf.broker_pool_limit = settings.celery_broker_pool_limit
celery_app.conf.worker_prefetch_multiplier = settings.celery_worker_prefetch_multiplier

# RabbitMQ broker konfigürasyonu
celery_app.conf.broker_connection_retry_on_startup = True
celery_app.conf.broker_connection_retry = True
celery_app.conf.broker_connection_max_retries = 10
celery_app.conf.broker_heartbeat = 30
celery_app.conf.broker_transport_options = {
    "priority_steps": list(range(10)),
    "sep": ":",
    "queue_order_strategy": "priority",
    "visibility_timeout": 43200,  # 12 saat
}
celery_app.conf.task_annotations = {
    "app.tasks.assembly.assembly_generate": {"rate_limit": appset.rate_limits.get("assembly", "6/m")},
    "app.tasks.cam.cam_generate": {"rate_limit": appset.rate_limits.get("cam", "12/m")},
    "app.tasks.sim.sim_generate": {"rate_limit": appset.rate_limits.get("sim", "4/m")},
}
# Task routing ve priority konfigürasyonu
celery_app.conf.task_routes = {
    "app.tasks.cad.*": {
        "queue": "freecad",
        "priority": settings.queue_priority_high,
        "routing_key": "freecad"
    },
    "app.tasks.cam_build.*": {
        "queue": "freecad",
        "priority": settings.queue_priority_high,
        "routing_key": "freecad"
    },
    "app.tasks.m18_cam.*": {
        "queue": "freecad",
        "priority": settings.queue_priority_high,
        "routing_key": "freecad"
    },
    "app.tasks.assembly.*": {
        "queue": "freecad",
        "priority": settings.queue_priority_urgent,
        "routing_key": "freecad"
    },
    "app.tasks.m18_sim.*": {
        "queue": "sim",
        "priority": settings.queue_priority_high,
        "routing_key": "sim"
    },
    "app.tasks.sim.*": {
        "queue": "sim",
        "priority": settings.queue_priority_normal,
        "routing_key": "sim"
    },
    "app.tasks.m18_post.*": {
        "queue": "postproc",
        "priority": settings.queue_priority_low,
        "routing_key": "postproc"
    },
    "app.tasks.reports.*": {
        "queue": "postproc",
        "priority": settings.queue_priority_low,
        "routing_key": "postproc"
    },
    "app.tasks.cam.*": {
        "queue": "cpu",
        "priority": settings.queue_priority_normal,
        "routing_key": "cpu"
    },
    "app.tasks.design.*": {
        "queue": "cpu",
        "priority": settings.queue_priority_normal,
        "routing_key": "cpu"
    },
    "app.tasks.maintenance.*": {
        "queue": "postproc",
        "priority": settings.queue_priority_background,
        "routing_key": "postproc"
    },
    "app.tasks.monitoring.*": {
        "queue": "cpu",
        "priority": settings.queue_priority_background,
        "routing_key": "cpu"
    },
}


# Celery Beat Schedule konfigürasyonu
celery_app.conf.beat_schedule = {
    # Sistem sağlık kontrolü - her 5 dakikada
    "health-check": {
        "task": "app.tasks.maintenance.health_check",
        "schedule": 300.0,  # 5 dakika
        "options": {
            "queue": "cpu",
            "priority": settings.queue_priority_background
        }
    },
    # Geçici dosya temizleme - günde bir
    "cleanup-temp-files": {
        "task": "app.tasks.maintenance.cleanup_temp_files",
        "schedule": 86400.0,  # 24 saat
        "options": {
            "queue": "postproc",
            "priority": settings.queue_priority_background
        }
    },
    # Queue metrikleri toplama - her dakika
    "collect-queue-metrics": {
        "task": "app.tasks.monitoring.collect_queue_metrics",
        "schedule": 60.0,  # 1 dakika
        "options": {
            "queue": "cpu",
            "priority": settings.queue_priority_background
        }
    },
    # Dead Letter Queue temizleme - saatte bir
    "cleanup-dlq": {
        "task": "app.tasks.maintenance.cleanup_dead_letter_queue",
        "schedule": 3600.0,  # 1 saat
        "options": {
            "queue": "postproc",
            "priority": settings.queue_priority_background
        }
    },
    # FreeCAD process sağlık kontrolü - 10 dakikada bir
    "freecad-health-check": {
        "task": "app.tasks.monitoring.freecad_health_check",
        "schedule": 600.0,  # 10 dakika
        "options": {
            "queue": "freecad",
            "priority": settings.queue_priority_background
        }
    },
}

celery_app.conf.timezone = "UTC"

# Error handling konfigürasyonu
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.result_expires = 3600  # 1 saat

# Worker konfigürasyonu
celery_app.conf.worker_disable_rate_limits = False
celery_app.conf.worker_enable_remote_control = True
celery_app.conf.worker_send_task_events = True
celery_app.conf.task_send_sent_event = True

# API prosesi içinde shared_task çağrılarının doğru broker'a publish edebilmesi için
try:  # pragma: no cover
    celery_app.set_default()
except Exception:
    pass

