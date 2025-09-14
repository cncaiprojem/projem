"""
Task 7.26: Pydantic Schemas for Backup and Recovery

Request and response schemas for backup/recovery API endpoints.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


# Base schemas
class BackupPolicyBase(BaseModel):
    """Base schema for backup policy."""
    name: str = Field(..., min_length=1, max_length=255, description="Policy name")
    type: str = Field(..., description="Policy type: time_based, version_based, legal_hold, compliance")
    retention_days: Optional[int] = Field(None, ge=1, le=3650, description="Retention in days")
    retention_versions: Optional[int] = Field(None, ge=1, le=1000, description="Number of versions to keep")
    legal_hold_until: Optional[datetime] = Field(None, description="Legal hold expiration")
    compliance_mode: bool = Field(False, description="Compliance mode (cannot be shortened)")
    priority: str = Field("medium", description="Priority: critical, high, medium, low")
    tags: List[str] = Field(default_factory=list, description="Tags for categorization")

    @field_validator('type')
    @classmethod
    def validate_type(cls, v: str) -> str:
        valid_types = ["time_based", "version_based", "legal_hold", "compliance"]
        if v not in valid_types:
            raise ValueError(f"Type must be one of {valid_types}")
        return v

    @field_validator('priority')
    @classmethod
    def validate_priority(cls, v: str) -> str:
        valid_priorities = ["critical", "high", "medium", "low"]
        if v not in valid_priorities:
            raise ValueError(f"Priority must be one of {valid_priorities}")
        return v


class BackupPolicyCreate(BackupPolicyBase):
    """Schema for creating backup policy."""
    pass


class BackupPolicyUpdate(BaseModel):
    """Schema for updating backup policy."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    retention_days: Optional[int] = Field(None, ge=1, le=3650)
    retention_versions: Optional[int] = Field(None, ge=1, le=1000)
    legal_hold_until: Optional[datetime] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None


class BackupPolicyResponse(BackupPolicyBase):
    """Schema for backup policy response."""
    id: int
    policy_id: str
    created_at: datetime
    updated_at: datetime
    created_by_id: Optional[int]

    class Config:
        from_attributes = True


# Backup snapshot schemas
class BackupSnapshotBase(BaseModel):
    """Base schema for backup snapshot."""
    source_id: str = Field(..., description="Source document/model ID")
    backup_type: str = Field("full", description="Backup type: full, incremental, differential, synthetic")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")


class BackupSnapshotCreate(BackupSnapshotBase):
    """Schema for creating backup snapshot."""
    policy_id: Optional[int] = Field(None, description="Associated policy ID")
    compression_enabled: bool = Field(True, description="Enable compression")
    encryption_enabled: bool = Field(True, description="Enable encryption")
    verify_after_backup: bool = Field(True, description="Verify backup after creation")


class BackupSnapshotResponse(BackupSnapshotBase):
    """Schema for backup snapshot response."""
    id: int
    backup_id: str
    size_bytes: int
    compressed_size_bytes: Optional[int]
    checksum: str
    encryption_method: str
    compression_algorithm: str
    storage_tier: str
    storage_path: str
    verification_status: Optional[str]
    verification_date: Optional[datetime]
    created_at: datetime
    expires_at: Optional[datetime]
    policy_id: Optional[int]
    job_id: Optional[int]

    class Config:
        from_attributes = True


# Recovery operation schemas
class RecoveryRequestBase(BaseModel):
    """Base schema for recovery request."""
    recovery_type: str = Field(..., description="Type: backup_restore, pitr, disaster_recovery, model_recovery")
    source_id: str = Field(..., description="Source to recover")
    recovery_mode: str = Field("latest", description="Mode: exact_time, transaction, checkpoint, latest")
    target_timestamp: Optional[datetime] = Field(None, description="Target recovery time")
    target_transaction_id: Optional[str] = Field(None, description="Target transaction ID")
    dry_run: bool = Field(False, description="Preview without applying")


class RecoveryOperationCreate(RecoveryRequestBase):
    """Schema for creating recovery operation."""
    backup_id: Optional[int] = Field(None, description="Specific backup to restore")
    conflict_resolution: str = Field("theirs", description="Conflict resolution: ours, theirs, merge, manual")


class RecoveryOperationUpdate(BaseModel):
    """Schema for updating recovery operation."""
    status: Optional[str] = Field(None, description="Status update")
    progress: Optional[float] = Field(None, ge=0.0, le=1.0, description="Progress 0-1")
    errors: Optional[List[str]] = None
    warnings: Optional[List[str]] = None


class RecoveryOperationResponse(RecoveryRequestBase):
    """Schema for recovery operation response."""
    id: int
    operation_id: str
    status: str
    progress: float
    success: Optional[bool]
    recovered_objects: int
    data_loss_minutes: Optional[int]
    actual_recovery_minutes: Optional[int]
    errors: List[str]
    warnings: List[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime
    backup_id: Optional[int]
    disaster_event_id: Optional[int]
    job_id: Optional[int]

    class Config:
        from_attributes = True


# Disaster event schemas
class DisasterEventBase(BaseModel):
    """Base schema for disaster event."""
    disaster_type: str = Field(..., description="Type: hardware_failure, network_outage, etc.")
    severity: str = Field(..., description="Severity: critical, high, medium, low")
    description: str = Field(..., min_length=1, description="Event description")
    impacted_components: List[str] = Field(default_factory=list, description="Affected components")


class DisasterEventCreate(DisasterEventBase):
    """Schema for creating disaster event."""
    estimated_downtime_minutes: Optional[int] = Field(None, ge=0, description="Estimated downtime")
    auto_recover: bool = Field(False, description="Attempt automatic recovery")


class DisasterEventUpdate(BaseModel):
    """Schema for updating disaster event."""
    recovery_state: Optional[str] = None
    actual_downtime_minutes: Optional[int] = None
    data_loss_detected: Optional[bool] = None


class DisasterEventResponse(DisasterEventBase):
    """Schema for disaster event response."""
    id: int
    event_id: str
    recovery_plan_id: Optional[str]
    recovery_state: Optional[str]
    rto_target_minutes: Optional[int]
    rpo_target_minutes: Optional[int]
    actual_recovery_minutes: Optional[int]
    actual_downtime_minutes: Optional[int]
    data_loss_detected: bool
    notifications_sent: List[Dict[str, Any]]
    detected_at: datetime
    recovery_started_at: Optional[datetime]
    recovery_completed_at: Optional[datetime]

    class Config:
        from_attributes = True


# Backup schedule schemas
class BackupScheduleBase(BaseModel):
    """Base schema for backup schedule."""
    name: str = Field(..., min_length=1, max_length=255, description="Schedule name")
    source_pattern: str = Field(..., description="Pattern for sources to backup")
    cron_expression: str = Field(..., description="Cron expression for scheduling")
    priority: str = Field("medium", description="Priority level")
    enabled: bool = Field(True, description="Enable schedule")
    max_runtime_minutes: int = Field(120, ge=1, le=1440, description="Max runtime")
    retry_on_failure: bool = Field(True, description="Retry on failure")
    retry_count: int = Field(3, ge=0, le=10, description="Number of retries")


class BackupScheduleCreate(BackupScheduleBase):
    """Schema for creating backup schedule."""
    policy_id: Optional[int] = Field(None, description="Associated policy ID")
    backup_type: str = Field("incremental", description="Backup type")
    compression_enabled: bool = Field(True, description="Enable compression")
    encryption_enabled: bool = Field(True, description="Enable encryption")
    verify_after_backup: bool = Field(True, description="Verify after backup")
    tags: List[str] = Field(default_factory=list, description="Tags")


class BackupScheduleUpdate(BaseModel):
    """Schema for updating backup schedule."""
    name: Optional[str] = None
    cron_expression: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[str] = None
    tags: Optional[List[str]] = None


class BackupScheduleResponse(BackupScheduleBase):
    """Schema for backup schedule response."""
    id: int
    schedule_id: str
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    last_status: Optional[str]
    consecutive_failures: int
    backup_type: str
    compression_enabled: bool
    encryption_enabled: bool
    verify_after_backup: bool
    tags: List[str]
    created_at: datetime
    updated_at: datetime
    policy_id: Optional[int]

    class Config:
        from_attributes = True


# Model recovery schemas
class ModelRecoveryRequest(BaseModel):
    """Schema for model recovery request."""
    document_id: str = Field(..., description="Document ID to recover")
    recovery_strategy: Optional[str] = Field(
        None,
        description="Strategy: auto_repair, rebuild_features, restore_backup, partial_recovery"
    )
    backup_id: Optional[str] = Field(None, description="Specific backup to use")
    validation_level: str = Field("full", description="Validation level: basic, geometry, topology, constraints, full")


class ModelRecoveryReportResponse(BaseModel):
    """Schema for model recovery report response."""
    id: int
    report_id: str
    document_id: str
    corruption_type: Optional[str]
    corruption_severity: Optional[str]
    affected_features: List[str]
    recovery_strategy: Optional[str]
    recovery_steps: List[Dict[str, Any]]
    success: bool
    recovered_features: int
    lost_features: int
    validation_passed: bool
    duration_seconds: float
    errors: List[str]
    warnings: List[str]
    recovery_timestamp: datetime
    job_id: Optional[int]

    class Config:
        from_attributes = True


# Batch operation schemas
class BatchBackupRequest(BaseModel):
    """Schema for batch backup request."""
    source_ids: List[str] = Field(..., min_items=1, max_items=100, description="Sources to backup")
    backup_type: str = Field("incremental", description="Backup type")
    policy_id: Optional[int] = Field(None, description="Policy to apply")
    parallel: bool = Field(True, description="Process in parallel")


class BatchRecoveryRequest(BaseModel):
    """Schema for batch recovery request."""
    source_ids: List[str] = Field(..., min_items=1, max_items=100, description="Sources to recover")
    recovery_mode: str = Field("latest", description="Recovery mode")
    target_timestamp: Optional[datetime] = None
    parallel: bool = Field(True, description="Process in parallel")


# Status and metrics schemas
class BackupStatusResponse(BaseModel):
    """Schema for backup status response."""
    total_backups: int
    total_size_bytes: int
    backups_by_type: Dict[str, int]
    backups_by_tier: Dict[str, int]
    oldest_backup: Optional[datetime]
    newest_backup: Optional[datetime]
    deduplication_ratio: float
    compression_ratio: float


class RecoveryMetricsResponse(BaseModel):
    """Schema for recovery metrics response."""
    total_recoveries: int
    successful_recoveries: int
    failed_recoveries: int
    average_recovery_time_minutes: float
    rto_compliance_rate: float
    rpo_compliance_rate: float
    mttr: float  # Mean Time To Recovery
    mtbf: float  # Mean Time Between Failures
    recent_events: List[Dict[str, Any]]


class HealthCheckResponse(BaseModel):
    """Schema for health check response."""
    component: str
    status: str  # healthy, degraded, unhealthy, unknown
    last_check: datetime
    failure_count: int
    success_count: int
    details: Dict[str, Any]