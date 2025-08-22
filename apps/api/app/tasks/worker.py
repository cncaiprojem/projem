"""
Task 6.1: Updated Celery Worker Configuration
Uses new centralized celery_app from core.celery_app with proper DLX/DLQ topology.
"""

from __future__ import annotations

# Task 6.1: Import centralized Celery app configuration
from ..core.celery_app import celery_app
from ..core.queue_constants import (
    MAIN_QUEUES,
    DLQ_QUEUES,
    LEGACY_QUEUE_MAPPING,
    QUEUE_DEFAULT,
    QUEUE_MODEL,
    QUEUE_CAM,
    QUEUE_SIM,
    QUEUE_REPORT,
    QUEUE_ERP,
)

# Task 6.1: All Celery configuration is now centralized in core.celery_app
# This file only imports the configured app for worker processes

# Legacy compatibility note: 
# Workers can still reference LEGACY_QUEUE_MAPPING for backward compatibility
# during migration period if needed

# Ensure task discovery runs
try:  # pragma: no cover
    celery_app.autodiscover_tasks(["app.tasks"])  # type: ignore[arg-type]
except Exception:
    pass

# Ensure default app is set for shared_task decorators
try:  # pragma: no cover
    celery_app.set_default()
except Exception:
    pass

