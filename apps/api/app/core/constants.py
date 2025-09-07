"""
Shared constants for API modules.

This module centralizes commonly used constants to follow DRY principles
and improve maintainability across the codebase.
"""

from ..models.enums import JobStatus
from ..schemas.progress import ExportFormat

# Terminal job statuses - jobs in these states will not receive further updates
TERMINAL_STATUSES = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.TIMEOUT.value
}

# Export format mapping for file conversions
# Maps file extensions to ExportFormat enum values
FORMAT_MAP = {
    "step": ExportFormat.STEP,
    "stp": ExportFormat.STEP,
    "stl": ExportFormat.STL,
    "fcstd": ExportFormat.FCSTD,
    "fcstd1": ExportFormat.FCSTD,
    "iges": ExportFormat.IGES,
    "igs": ExportFormat.IGES,
    "obj": ExportFormat.OBJ,
    "glb": ExportFormat.GLB,
    "brep": ExportFormat.BREP,
}

# WebSocket and SSE configuration
PROGRESS_CHANNEL_PREFIX = "job:progress:"
PROGRESS_ALL_CHANNEL = "job:progress:*"
PROGRESS_CACHE_TTL = 3600  # 1 hour in seconds
PROGRESS_CACHE_MAX_EVENTS = 1000  # Maximum events to cache per job

# Throttling configuration for progress updates
THROTTLE_INTERVAL_MS = 500  # Max 1 update per 500ms per job
MILESTONE_BYPASS_THROTTLE = True  # Milestone events bypass throttling

# SSE keepalive configuration
SSE_KEEPALIVE_INTERVAL = 30.0  # Send keepalive every 30 seconds

# WebSocket retry configuration
WS_RETRY_AFTER_ERROR = 5000  # Retry after 5 seconds on error
WS_RETRY_AFTER_DISCONNECT = 1000  # Retry after 1 second on disconnect