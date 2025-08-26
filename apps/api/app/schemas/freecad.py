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


# Document Manager Response Models for Task 7.19

class DocumentMetadataResponse(BaseModel):
    """Document metadata response."""
    document_id: str = Field(description="Unique document identifier")
    job_id: str = Field(description="Associated job ID")
    version: int = Field(description="Document version number")
    revision: str = Field(description="Document revision letter")
    created_at: datetime = Field(description="Creation timestamp")
    modified_at: datetime = Field(description="Last modification timestamp")
    author: Optional[str] = Field(default=None, description="Document author")
    description: Optional[str] = Field(default=None, description="Document description")
    file_size_bytes: Optional[int] = Field(default=None, description="File size in bytes")
    compressed: bool = Field(default=False, description="Whether document is compressed")
    
    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "doc_job123",
                "job_id": "job123",
                "version": 1,
                "revision": "A",
                "created_at": "2024-01-15T10:30:00Z",
                "modified_at": "2024-01-15T11:00:00Z",
                "author": "user@example.com",
                "description": "3D model for part A",
                "file_size_bytes": 1048576,
                "compressed": True
            }
        }


class DocumentLockResponse(BaseModel):
    """Document lock response."""
    document_id: str = Field(description="Locked document ID")
    lock_id: str = Field(description="Unique lock identifier")
    owner_id: str = Field(description="Lock owner identifier")
    acquired_at: datetime = Field(description="Lock acquisition time")
    expires_at: Optional[datetime] = Field(default=None, description="Lock expiration time")
    lock_type: str = Field(default="exclusive", description="Lock type")
    
    class Config:
        json_schema_extra = {
            "example": {
                "document_id": "doc_job123",
                "lock_id": "lock_doc_job123_user1_1705315800000000",
                "owner_id": "user1",
                "acquired_at": "2024-01-15T10:30:00Z",
                "expires_at": "2024-01-15T11:30:00Z",
                "lock_type": "exclusive"
            }
        }


class DocumentTransactionResponse(BaseModel):
    """Document transaction response."""
    transaction_id: str = Field(description="Unique transaction identifier")
    document_id: str = Field(description="Document in transaction")
    state: str = Field(description="Transaction state")
    started_at: Optional[datetime] = Field(default=None, description="Transaction start time")
    operations_count: int = Field(default=0, description="Number of operations in transaction")
    
    class Config:
        json_schema_extra = {
            "example": {
                "transaction_id": "txn_doc_job123_1705315800000000",
                "document_id": "doc_job123",
                "state": "active",
                "started_at": "2024-01-15T10:30:00Z",
                "operations_count": 5
            }
        }


class DocumentLockStatus(BaseModel):
    """Document lock status model."""
    locked: bool = Field(description="Whether document is locked")
    lock_id: str = Field(description="Lock identifier")
    owner: str = Field(description="Lock owner identifier")
    expires_at: Optional[str] = Field(default=None, description="Lock expiration time")
    is_expired: bool = Field(description="Whether lock has expired")


class DocumentTransactionStatus(BaseModel):
    """Document transaction status model."""
    transaction_id: str = Field(description="Transaction identifier")
    state: str = Field(description="Transaction state")
    started_at: Optional[str] = Field(default=None, description="Transaction start time")
    operations: int = Field(description="Number of operations in transaction")


class AssemblyStatus(BaseModel):
    """Assembly coordination status model."""
    is_assembly: bool = Field(description="Whether document is an assembly")
    parent: Optional[str] = Field(default=None, description="Parent document ID")
    children: List[str] = Field(default_factory=list, description="Child document IDs")
    constraints: int = Field(description="Number of constraints")


class DocumentStatusResponse(BaseModel):
    """Comprehensive document status response."""
    status: str = Field(description="Document status")
    document_id: str = Field(description="Document identifier")
    metadata: Optional[DocumentMetadataResponse] = Field(default=None, description="Document metadata")
    lock: Optional[DocumentLockStatus] = Field(default=None, description="Lock information if locked")
    transactions: List[DocumentTransactionStatus] = Field(default_factory=list, description="Active transactions")
    undo_stack_size: int = Field(default=0, description="Number of undo operations available")
    redo_stack_size: int = Field(default=0, description="Number of redo operations available")
    assembly: Optional[AssemblyStatus] = Field(default=None, description="Assembly coordination info")
    backup_count: int = Field(default=0, description="Number of available backups")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "open",
                "document_id": "doc_job123",
                "metadata": {
                    "document_id": "doc_job123",
                    "job_id": "job123",
                    "version": 1,
                    "revision": "B",
                    "created_at": "2024-01-15T10:30:00Z",
                    "modified_at": "2024-01-15T11:00:00Z"
                },
                "lock": None,
                "transactions": [],
                "undo_stack_size": 10,
                "redo_stack_size": 2,
                "assembly": None,
                "backup_count": 3
            }
        }


class DocumentBackupResponse(BaseModel):
    """Document backup response."""
    backup_id: str = Field(description="Backup identifier")
    document_id: str = Field(description="Original document ID")
    created_at: datetime = Field(description="Backup creation time")
    size_bytes: int = Field(description="Backup size in bytes")
    compressed: bool = Field(default=True, description="Whether backup is compressed")
    retention_days: int = Field(default=30, description="Backup retention period")
    
    class Config:
        json_schema_extra = {
            "example": {
                "backup_id": "backup_doc_job123_20240115_103000",
                "document_id": "doc_job123",
                "created_at": "2024-01-15T10:30:00Z",
                "size_bytes": 524288,
                "compressed": True,
                "retention_days": 30
            }
        }


class DocumentMigrationResponse(BaseModel):
    """Document migration response."""
    migration_id: str = Field(description="Migration identifier")
    source_version: str = Field(description="Source FreeCAD version")
    target_version: str = Field(description="Target FreeCAD version")
    status: str = Field(description="Migration status")
    started_at: Optional[datetime] = Field(default=None, description="Migration start time")
    completed_at: Optional[datetime] = Field(default=None, description="Migration completion time")
    changes_applied: int = Field(default=0, description="Number of changes applied")
    warnings: List[str] = Field(default_factory=list, description="Migration warnings")
    errors: List[str] = Field(default_factory=list, description="Migration errors")
    
    class Config:
        json_schema_extra = {
            "example": {
                "migration_id": "mig_doc_job123_1705315800",
                "source_version": "1.1.0",
                "target_version": "1.2.0",
                "status": "completed",
                "started_at": "2024-01-15T10:30:00Z",
                "completed_at": "2024-01-15T10:31:00Z",
                "changes_applied": 5,
                "warnings": [],
                "errors": []
            }
        }