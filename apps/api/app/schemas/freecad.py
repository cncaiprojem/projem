"""
Pydantic schemas for FreeCAD service API responses.

This module defines structured response models for all FreeCAD-related
API endpoints to ensure type safety and automatic OpenAPI documentation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class FreeCADHealthStatus(BaseModel):
    """FreeCAD service availability and version information."""
    available: bool = Field(description="Whether FreeCAD is available")
    path: Optional[str] = Field(default=None, description="Path to FreeCAD executable")
    version: Optional[str] = Field(default=None, description="FreeCAD version")
    version_valid: Optional[bool] = Field(default=None, description="Whether version meets requirements")
    error: Optional[str] = Field(default=None, description="Error message if unavailable")


class CircuitBreakerStatus(BaseModel):
    """Circuit breaker state information."""
    state: str = Field(description="Current state: CLOSED, OPEN, or HALF_OPEN")
    failure_count: int = Field(description="Number of consecutive failures")
    last_failure: Optional[float] = Field(default=None, description="Timestamp of last failure")


class ActiveProcessesStatus(BaseModel):
    """Active FreeCAD processes information."""
    count: int = Field(description="Number of active processes")
    processes: List[str] = Field(default_factory=list, description="List of process identifiers")


class ResourceConfiguration(BaseModel):
    """Resource configuration settings."""
    max_concurrent_operations: int = Field(description="Maximum concurrent operations allowed")
    circuit_breaker_threshold: int = Field(description="Failure threshold for circuit breaker")
    circuit_breaker_recovery_timeout: int = Field(description="Recovery timeout in seconds")


class HealthCheckStatus(BaseModel):
    """Comprehensive health check status details."""
    freecad: FreeCADHealthStatus = Field(description="FreeCAD availability status")
    circuit_breaker: CircuitBreakerStatus = Field(description="Circuit breaker status")
    active_processes: ActiveProcessesStatus = Field(description="Active processes status")
    resource_configuration: ResourceConfiguration = Field(description="Resource configuration")


class FreeCADHealthCheckResponse(BaseModel):
    """Response model for FreeCAD health check endpoint."""
    healthy: bool = Field(description="Overall health status")
    checks: HealthCheckStatus = Field(description="Detailed health checks")
    timestamp: datetime = Field(description="Timestamp of health check")
    version: str = Field(description="Service version")
    error: Optional[str] = Field(default=None, description="Error message if unhealthy")
    
    class Config:
        json_schema_extra = {
            "example": {
                "healthy": True,
                "checks": {
                    "freecad": {
                        "available": True,
                        "path": "/usr/bin/FreeCADCmd",
                        "version": "1.1.0",
                        "version_valid": True
                    },
                    "circuit_breaker": {
                        "state": "CLOSED",
                        "failure_count": 0,
                        "last_failure": None
                    },
                    "active_processes": {
                        "count": 2,
                        "processes": ["abc123_12345", "def456_67890"]
                    },
                    "resource_configuration": {
                        "max_concurrent_operations": 4,
                        "circuit_breaker_threshold": 5,
                        "circuit_breaker_recovery_timeout": 60
                    }
                },
                "timestamp": "2024-01-15T10:30:00Z",
                "version": "1.0.0"
            }
        }


class MetricsSummaryResponse(BaseModel):
    """Response model for FreeCAD metrics endpoint."""
    active_processes: int = Field(description="Number of currently active processes")
    circuit_breaker_state: str = Field(description="Current circuit breaker state")
    circuit_breaker_failures: int = Field(description="Number of circuit breaker failures")
    timestamp: datetime = Field(description="Timestamp of metrics collection")
    
    class Config:
        json_schema_extra = {
            "example": {
                "active_processes": 3,
                "circuit_breaker_state": "CLOSED",
                "circuit_breaker_failures": 0,
                "timestamp": "2024-01-15T10:30:00Z"
            }
        }


class CircuitBreakerResetResponse(BaseModel):
    """Response model for circuit breaker reset endpoint."""
    success: bool = Field(description="Whether reset was successful")
    message: str = Field(description="Success message in English")
    turkish_message: str = Field(description="Success message in Turkish")
    new_state: str = Field(description="New circuit breaker state after reset")
    
    class Config:
        json_schema_extra = {
            "example": {
                "success": True,
                "message": "Circuit breaker reset successfully",
                "turkish_message": "Devre kesici başarıyla sıfırlandı",
                "new_state": "CLOSED"
            }
        }