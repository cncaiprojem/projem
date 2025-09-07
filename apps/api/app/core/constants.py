"""
Core constants for the API application.

This module defines application-wide constants that are used across various services.
Constants can be overridden via environment variables where appropriate.
"""

import os
from typing import Final

# Model Generation Constants (Task 7.17)
# These thresholds are used for alerting and monitoring

# OCCT memory threshold: 1.5 GiB default (1.5 * 1024^3 bytes)
# Can be overridden via OCCT_HIGH_MEMORY_THRESHOLD_BYTES environment variable
OCCT_HIGH_MEMORY_THRESHOLD_BYTES: Final[int] = int(
    os.getenv("OCCT_HIGH_MEMORY_THRESHOLD_BYTES", "1610612736")
)

# Model generation stage timeout: 5 minutes (300 seconds)
# Used in Prometheus alerts for slow stage detection
MODEL_GENERATION_STAGE_TIMEOUT_SECONDS: Final[int] = int(
    os.getenv("MODEL_GENERATION_STAGE_TIMEOUT_SECONDS", "300")
)

# Assembly4 solver thresholds
ASSEMBLY4_SOLVER_SLOW_THRESHOLD_SECONDS: Final[int] = int(
    os.getenv("ASSEMBLY4_SOLVER_SLOW_THRESHOLD_SECONDS", "15")
)

ASSEMBLY4_EXCESSIVE_ITERATIONS_THRESHOLD: Final[int] = int(
    os.getenv("ASSEMBLY4_EXCESSIVE_ITERATIONS_THRESHOLD", "200")
)

# Export validation thresholds
EXPORT_VALIDATION_FAILURE_THRESHOLD_PERCENT: Final[float] = float(
    os.getenv("EXPORT_VALIDATION_FAILURE_THRESHOLD_PERCENT", "2.0")
)

# AI provider thresholds
AI_PROVIDER_LATENCY_THRESHOLD_SECONDS: Final[int] = int(
    os.getenv("AI_PROVIDER_LATENCY_THRESHOLD_SECONDS", "30")
)

AI_PROVIDER_ERROR_THRESHOLD_PERCENT: Final[float] = float(
    os.getenv("AI_PROVIDER_ERROR_THRESHOLD_PERCENT", "10.0")
)

# Worker operation thresholds
FREECAD_WORKER_RESTART_THRESHOLD_PER_SECOND: Final[float] = float(
    os.getenv("FREECAD_WORKER_RESTART_THRESHOLD_PER_SECOND", "0.1")
)

# Material library thresholds
MATERIAL_LIBRARY_ERROR_THRESHOLD_PERCENT: Final[float] = float(
    os.getenv("MATERIAL_LIBRARY_ERROR_THRESHOLD_PERCENT", "5.0")
)

# Workbench compatibility thresholds
WORKBENCH_INCOMPATIBILITY_THRESHOLD_PERCENT: Final[float] = float(
    os.getenv("WORKBENCH_INCOMPATIBILITY_THRESHOLD_PERCENT", "5.0")
)

__all__ = [
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