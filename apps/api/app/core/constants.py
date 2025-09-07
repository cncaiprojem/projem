"""
Core constants for the API application.

This module defines application-wide constants that are used across various services.
Constants can be overridden via environment variables where appropriate.
"""

from typing import Final
from .env_utils import safe_parse_int, safe_parse_float

# Model Generation Constants (Task 7.17)
# These thresholds are used for alerting and monitoring

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
EXPORT_VALIDATION_FAILURE_THRESHOLD_PERCENT: Final[float] = safe_parse_float(
    env_var="EXPORT_VALIDATION_FAILURE_THRESHOLD_PERCENT",
    default=2.0,
    min_value=0.0,
    max_value=100.0,
    error_message="Export validation failure threshold must be between 0 and 100 percent"
)

# AI provider thresholds
AI_PROVIDER_LATENCY_THRESHOLD_SECONDS: Final[int] = safe_parse_int(
    env_var="AI_PROVIDER_LATENCY_THRESHOLD_SECONDS",
    default=30,
    min_value=1,
    max_value=300,
    error_message="AI provider latency threshold must be between 1 and 300 seconds"
)

AI_PROVIDER_ERROR_THRESHOLD_PERCENT: Final[float] = safe_parse_float(
    env_var="AI_PROVIDER_ERROR_THRESHOLD_PERCENT",
    default=10.0,
    min_value=0.0,
    max_value=100.0,
    error_message="AI provider error threshold must be between 0 and 100 percent"
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
MATERIAL_LIBRARY_ERROR_THRESHOLD_PERCENT: Final[float] = safe_parse_float(
    env_var="MATERIAL_LIBRARY_ERROR_THRESHOLD_PERCENT",
    default=5.0,
    min_value=0.0,
    max_value=100.0,
    error_message="Material library error threshold must be between 0 and 100 percent"
)

# Workbench compatibility thresholds
WORKBENCH_INCOMPATIBILITY_THRESHOLD_PERCENT: Final[float] = safe_parse_float(
    env_var="WORKBENCH_INCOMPATIBILITY_THRESHOLD_PERCENT",
    default=5.0,
    min_value=0.0,
    max_value=100.0,
    error_message="Workbench incompatibility threshold must be between 0 and 100 percent"
)

__all__ = [
    "DEFAULT_OCCT_MEMORY_THRESHOLD",
    "OCCT_HIGH_MEMORY_THRESHOLD_BYTES",
    "MODEL_GENERATION_STAGE_TIMEOUT_SECONDS",
    "ASSEMBLY4_SOLVER_SLOW_THRESHOLD_SECONDS",
    "ASSEMBLY4_EXCESSIVE_ITERATIONS_THRESHOLD",
    "EXPORT_VALIDATION_FAILURE_THRESHOLD_PERCENT",
    "AI_PROVIDER_LATENCY_THRESHOLD_SECONDS",
    "AI_PROVIDER_ERROR_THRESHOLD_PERCENT",
    "FREECAD_WORKER_RESTART_THRESHOLD_PER_SECOND",
    "MATERIAL_LIBRARY_ERROR_THRESHOLD_PERCENT",
    "WORKBENCH_INCOMPATIBILITY_THRESHOLD_PERCENT",
]