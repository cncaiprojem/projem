"""
Queue constants for Celery and RabbitMQ configuration.
Task 6.1: Updated queue topology with DLX/DLQ per-queue dead-lettering.
Centralized queue definitions to avoid duplication.
"""

# Task 6.1: Updated main queue names per specification
QUEUE_DEFAULT = "default"
QUEUE_MODEL = "model"
QUEUE_CAM = "cam"
QUEUE_SIM = "sim"
QUEUE_REPORT = "report"
QUEUE_ERP = "erp"

# Queue lists
MAIN_QUEUES = [QUEUE_DEFAULT, QUEUE_MODEL, QUEUE_CAM, QUEUE_SIM, QUEUE_REPORT, QUEUE_ERP]

# Task 6.1: Dead Letter Exchange and Queue names per specification
# Each primary queue gets its own DLX: <queue>.dlx and DLQ: <queue>_dlq
DLX_SUFFIX = ".dlx"
DLQ_SUFFIX = "_dlq"

DLX_EXCHANGES = [f"{q}{DLX_SUFFIX}" for q in MAIN_QUEUES]
DLQ_QUEUES = [f"{q}{DLQ_SUFFIX}" for q in MAIN_QUEUES]

# Combined list
ALL_QUEUES = MAIN_QUEUES + DLQ_QUEUES

# Task 6.1: Exchange configuration
JOBS_EXCHANGE = "jobs.direct"
JOBS_EXCHANGE_TYPE = "direct"

# Task 6.1: Routing key mappings
ROUTING_KEYS = {
    "jobs.ai": QUEUE_DEFAULT,
    "jobs.model": QUEUE_MODEL,
    "jobs.cam": QUEUE_CAM,
    "jobs.sim": QUEUE_SIM,
    "jobs.report": QUEUE_REPORT,
    "jobs.erp": QUEUE_ERP,
}

# Task 6.1: Queue configuration parameters
DLQ_CONFIG = {
    "ttl": 86400000,  # 24 hours in milliseconds
    "max_length": 10000,  # Maximum number of messages
    "queue_mode": "lazy",  # Classic lazy mode for DLQs
}

# Task 6.1: Primary queue configurations with quorum type
QUEUE_CONFIGS = {
    QUEUE_DEFAULT: {
        "ttl": 1800000,  # 30 minutes
        "priority": "normal",
        "queue_type": "quorum",  # Quorum queues for primaries
        "max_message_bytes": 10485760,  # 10MB message size limit
    },
    QUEUE_MODEL: {
        "ttl": 3600000,  # 1 hour - model generation can be slow
        "priority": "high",
        "queue_type": "quorum",
        "max_message_bytes": 10485760,
    },
    QUEUE_CAM: {
        "ttl": 2700000,  # 45 minutes - CAM processing
        "priority": "high",
        "queue_type": "quorum",
        "max_message_bytes": 10485760,
    },
    QUEUE_SIM: {
        "ttl": 3600000,  # 1 hour - simulation can be slow
        "priority": "high",
        "queue_type": "quorum",
        "max_message_bytes": 10485760,
    },
    QUEUE_REPORT: {
        "ttl": 900000,  # 15 minutes - report generation
        "priority": "low",
        "queue_type": "quorum",
        "max_message_bytes": 10485760,
    },
    QUEUE_ERP: {
        "ttl": 1800000,  # 30 minutes - ERP integration
        "priority": "normal",
        "queue_type": "quorum",
        "max_message_bytes": 10485760,
    },
}

# Legacy queue mapping for backward compatibility during migration
LEGACY_QUEUE_MAPPING = {
    "freecad": QUEUE_MODEL,  # FreeCAD tasks -> model queue
    "cpu": QUEUE_DEFAULT,    # CPU tasks -> default queue
    "postproc": QUEUE_REPORT,  # Post-processing -> report queue
}