"""
Queue constants for Celery and RabbitMQ configuration.
Centralized queue definitions to avoid duplication.
"""

# Main queue names
QUEUE_FREECAD = "freecad"
QUEUE_SIM = "sim"
QUEUE_CPU = "cpu"
QUEUE_POSTPROC = "postproc"

# Queue lists
MAIN_QUEUES = [QUEUE_FREECAD, QUEUE_SIM, QUEUE_CPU, QUEUE_POSTPROC]

# Dead Letter Queue names
DLQ_PREFIX = "dlq."
DLQ_QUEUES = [f"{DLQ_PREFIX}{q}" for q in MAIN_QUEUES]

# Combined list
ALL_QUEUES = MAIN_QUEUES + DLQ_QUEUES

# Queue configuration parameters
DLQ_CONFIG = {
    "ttl": 86400000,  # 24 hours in milliseconds
    "max_length": 10000,  # Maximum number of messages
}

# Queue TTL and retry configurations
QUEUE_CONFIGS = {
    QUEUE_FREECAD: {
        "ttl": 3600000,  # 1 hour
        "max_retries": 3,
        "priority": "high",
    },
    QUEUE_SIM: {
        "ttl": 3600000,  # 1 hour
        "max_retries": 3,
        "priority": "high",
    },
    QUEUE_CPU: {
        "ttl": 1800000,  # 30 minutes
        "max_retries": 2,
        "priority": "normal",
    },
    QUEUE_POSTPROC: {
        "ttl": 900000,  # 15 minutes
        "max_retries": 2,
        "priority": "low",
    },
}