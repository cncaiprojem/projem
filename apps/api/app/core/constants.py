"""
Core constants for the API application.

This module defines application-wide constants that are used across various services.
Constants can be overridden via environment variables where appropriate.
"""

from typing import Final
from .env_utils import safe_parse_int, safe_parse_float
from ..models.enums import JobStatus
from ..schemas.progress import ExportFormat

# ==============================================================================
# EXISTING CONSTANTS - Used by multiple services (WebSocket, SSE, Redis PubSub)
# ==============================================================================

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

# ==============================================================================
# Model Generation Constants (Task 7.17)
# These thresholds are used for alerting and monitoring
# ==============================================================================

# Default memory threshold: 1.5 GiB (1610612736 bytes = 1.5 * 1024^3)
DEFAULT_OCCT_MEMORY_THRESHOLD = 1610612736

# OCCT memory threshold: 1.5 GiB default (1.5 * 1024^3 bytes)
# Can be overridden via OCCT_HIGH_MEMORY_THRESHOLD_BYTES environment variable
# GEMINI HIGH SEVERITY: Added error handling for environment variable parsing
OCCT_HIGH_MEMORY_THRESHOLD_BYTES: Final[int] = safe_parse_int(
    env_var="OCCT_HIGH_MEMORY_THRESHOLD_BYTES",
    default=DEFAULT_OCCT_MEMORY_THRESHOLD,
    min_value=1,  # Must be positive
    error_message="OCCT memory threshold must be a positive integer"
)

# Model generation stage timeout: 5 minutes (300 seconds)
# Used in Prometheus alerts for slow stage detection
MODEL_GENERATION_STAGE_TIMEOUT_SECONDS: Final[int] = safe_parse_int(
    env_var="MODEL_GENERATION_STAGE_TIMEOUT_SECONDS",
    default=300,
    min_value=1,
    max_value=3600,  # Max 1 hour
    error_message="Model generation stage timeout must be between 1 and 3600 seconds"
)

# Assembly4 solver thresholds
ASSEMBLY4_SOLVER_SLOW_THRESHOLD_SECONDS: Final[int] = safe_parse_int(
    env_var="ASSEMBLY4_SOLVER_SLOW_THRESHOLD_SECONDS",
    default=15,
    min_value=1,
    max_value=300,  # Max 5 minutes
    error_message="Assembly4 solver slow threshold must be between 1 and 300 seconds"
)

ASSEMBLY4_EXCESSIVE_ITERATIONS_THRESHOLD: Final[int] = safe_parse_int(
    env_var="ASSEMBLY4_EXCESSIVE_ITERATIONS_THRESHOLD",
    default=200,
    min_value=1,
    max_value=10000,
    error_message="Assembly4 iterations threshold must be between 1 and 10000"
)

# Export validation thresholds
# GEMINI CRITICAL: Changed from percentage (0-100) to ratio (0-1) for Prometheus consistency
EXPORT_VALIDATION_FAILURE_THRESHOLD: Final[float] = safe_parse_float(
    env_var="EXPORT_VALIDATION_FAILURE_THRESHOLD",
    default=0.02,  # 2% as ratio
    min_value=0.0,
    max_value=1.0,
    error_message="Export validation failure threshold must be between 0.0 and 1.0"
)

# AI provider thresholds
AI_PROVIDER_LATENCY_THRESHOLD_SECONDS: Final[int] = safe_parse_int(
    env_var="AI_PROVIDER_LATENCY_THRESHOLD_SECONDS",
    default=30,
    min_value=1,
    max_value=300,
    error_message="AI provider latency threshold must be between 1 and 300 seconds"
)

# GEMINI CRITICAL: Changed from percentage (0-100) to ratio (0-1) for Prometheus consistency
AI_PROVIDER_ERROR_THRESHOLD: Final[float] = safe_parse_float(
    env_var="AI_PROVIDER_ERROR_THRESHOLD",
    default=0.1,  # 10% as ratio
    min_value=0.0,
    max_value=1.0,
    error_message="AI provider error threshold must be between 0.0 and 1.0"
)

# Worker operation thresholds
FREECAD_WORKER_RESTART_THRESHOLD_PER_SECOND: Final[float] = safe_parse_float(
    env_var="FREECAD_WORKER_RESTART_THRESHOLD_PER_SECOND",
    default=0.1,
    min_value=0.0,
    max_value=10.0,
    error_message="Worker restart threshold must be between 0 and 10 per second"
)

# Material library thresholds
# GEMINI CRITICAL: Changed from percentage (0-100) to ratio (0-1) for Prometheus consistency
MATERIAL_LIBRARY_ERROR_THRESHOLD: Final[float] = safe_parse_float(
    env_var="MATERIAL_LIBRARY_ERROR_THRESHOLD",
    default=0.05,  # 5% as ratio
    min_value=0.0,
    max_value=1.0,
    error_message="Material library error threshold must be between 0.0 and 1.0"
)

# Workbench compatibility thresholds
# GEMINI CRITICAL: Changed from percentage (0-100) to ratio (0-1) for Prometheus consistency
WORKBENCH_INCOMPATIBILITY_THRESHOLD: Final[float] = safe_parse_float(
    env_var="WORKBENCH_INCOMPATIBILITY_THRESHOLD",
    default=0.05,  # 5% as ratio
    min_value=0.0,
    max_value=1.0,
    error_message="Workbench incompatibility threshold must be between 0.0 and 1.0"
)

__all__ = [
    # Existing constants (restored)
    "TERMINAL_STATUSES",
    "FORMAT_MAP",
    "PROGRESS_CHANNEL_PREFIX",
    "PROGRESS_ALL_CHANNEL",
    "PROGRESS_CACHE_TTL",
    "PROGRESS_CACHE_MAX_EVENTS",
    "THROTTLE_INTERVAL_MS",
    "MILESTONE_BYPASS_THROTTLE",
    "SSE_KEEPALIVE_INTERVAL",
    "WS_RETRY_AFTER_ERROR",
    "WS_RETRY_AFTER_DISCONNECT",
    # Task 7.17 Model Generation Observability constants
    "DEFAULT_OCCT_MEMORY_THRESHOLD",
    "OCCT_HIGH_MEMORY_THRESHOLD_BYTES",
    "MODEL_GENERATION_STAGE_TIMEOUT_SECONDS",
    "ASSEMBLY4_SOLVER_SLOW_THRESHOLD_SECONDS",
    "ASSEMBLY4_EXCESSIVE_ITERATIONS_THRESHOLD",
    "EXPORT_VALIDATION_FAILURE_THRESHOLD",
    "AI_PROVIDER_LATENCY_THRESHOLD_SECONDS",
    "AI_PROVIDER_ERROR_THRESHOLD",
    "FREECAD_WORKER_RESTART_THRESHOLD_PER_SECOND",
    "MATERIAL_LIBRARY_ERROR_THRESHOLD",
    "WORKBENCH_INCOMPATIBILITY_THRESHOLD",
]