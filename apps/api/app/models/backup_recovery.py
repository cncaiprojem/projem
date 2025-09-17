"""
Task 7.26: Database Models for Backup and Recovery

SQLAlchemy models for backup, recovery, and disaster management.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint
)
from sqlalchemy.orm import relationship

from ..db.base_class import Base


class BackupPolicy(Base):
    """Backup retention policy model."""
    __tablename__ = "backup_policies"

    id = Column(Integer, primary_key=True, index=True)
    policy_id = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # time_based, version_based, legal_hold, compliance
    retention_days = Column(Integer)
    retention_versions = Column(Integer)
    legal_hold_until = Column(DateTime(timezone=True))
    compliance_mode = Column(Boolean, default=False)
    priority = Column(String(20), default="medium")
    tags = Column(JSON, default=list)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    created_by_id = Column(Integer, ForeignKey("users.id"))

    # Relationships
    created_by = relationship("User", back_populates="backup_policies")
    backups = relationship("BackupSnapshot", back_populates="policy")


class BackupSnapshot(Base):
    """Backup snapshot model."""
    __tablename__ = "backup_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    backup_id = Column(String(100), unique=True, index=True, nullable=False)
    source_id = Column(String(100), index=True, nullable=False)  # Document/model ID
    backup_type = Column(String(20), nullable=False)  # full, incremental, differential, synthetic
    size_bytes = Column(BigInteger, nullable=False)
    compressed_size_bytes = Column(BigInteger)
    checksum = Column(String(64), nullable=False)
    encryption_method = Column(String(20), default="none")
    compression_algorithm = Column(String(20), default="none")
    storage_tier = Column(String(20), default="hot")  # hot, warm, cold, glacier
    storage_path = Column(String(500), nullable=False)

    # Recovery info
    recovery_point_objective = Column(Integer)  # RPO in minutes
    recovery_time_objective = Column(Integer)  # RTO in minutes

    # Metadata
    verification_status = Column(String(20))  # valid, corrupted, error
    verification_date = Column(DateTime(timezone=True))
    last_accessed = Column(DateTime(timezone=True))
    metadata = Column(JSON, default=dict)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime(timezone=True))

    # Foreign keys
    policy_id = Column(Integer, ForeignKey("backup_policies.id"))
    created_by_id = Column(Integer, ForeignKey("users.id"))
    job_id = Column(Integer, ForeignKey("jobs.id"))

    # Relationships
    policy = relationship("BackupPolicy", back_populates="backups")
    created_by = relationship("User", back_populates="backup_snapshots")
    job = relationship("Job", back_populates="backup_snapshots")
    recovery_operations = relationship("RecoveryOperation", back_populates="backup")

    # Indexes
    __table_args__ = (
        Index("ix_backup_snapshots_source_created", "source_id", "created_at"),
        Index("ix_backup_snapshots_tier_expires", "storage_tier", "expires_at"),
    )


class RecoveryOperation(Base):
    """Recovery operation record."""
    __tablename__ = "recovery_operations"

    id = Column(Integer, primary_key=True, index=True)
    operation_id = Column(String(100), unique=True, index=True, nullable=False)
    recovery_type = Column(String(50), nullable=False)  # backup_restore, pitr, disaster_recovery, model_recovery
    source_id = Column(String(100), index=True, nullable=False)

    # Recovery details
    recovery_mode = Column(String(50))  # exact_time, transaction, checkpoint, latest
    target_timestamp = Column(DateTime(timezone=True))
    target_transaction_id = Column(String(100))

    # Status
    status = Column(String(20), nullable=False, default="pending")  # pending, running, completed, failed
    progress = Column(Float, default=0.0)

    # Results
    success = Column(Boolean)
    recovered_objects = Column(Integer, default=0)
    data_loss_minutes = Column(Integer)
    actual_recovery_minutes = Column(Integer)

    # Errors and warnings
    errors = Column(JSON, default=list)
    warnings = Column(JSON, default=list)

    # Timestamps
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Foreign keys
    backup_id = Column(Integer, ForeignKey("backup_snapshots.id"))
    disaster_event_id = Column(Integer, ForeignKey("disaster_events.id"))
    initiated_by_id = Column(Integer, ForeignKey("users.id"))
    job_id = Column(Integer, ForeignKey("jobs.id"))

    # Relationships
    backup = relationship("BackupSnapshot", back_populates="recovery_operations")
    disaster_event = relationship("DisasterEvent", back_populates="recovery_operations")
    initiated_by = relationship("User", back_populates="recovery_operations")
    job = relationship("Job", back_populates="recovery_operations")

    # Indexes
    __table_args__ = (
        Index("ix_recovery_operations_status_started", "status", "started_at"),
    )


class DisasterEvent(Base):
    """Disaster event record."""
    __tablename__ = "disaster_events"

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String(100), unique=True, index=True, nullable=False)
    disaster_type = Column(String(50), nullable=False)  # hardware_failure, network_outage, etc.
    severity = Column(String(20), nullable=False)  # critical, high, medium, low
    description = Column(Text, nullable=False)

    # Impact
    impacted_components = Column(JSON, default=list)
    estimated_downtime_minutes = Column(Integer)
    actual_downtime_minutes = Column(Integer)
    data_loss_detected = Column(Boolean, default=False)

    # Recovery
    recovery_plan_id = Column(String(100))
    recovery_state = Column(String(20))  # detecting, assessing, recovering, completed, failed
    rto_target_minutes = Column(Integer)
    rpo_target_minutes = Column(Integer)
    actual_recovery_minutes = Column(Integer)

    # Notifications
    notifications_sent = Column(JSON, default=list)

    # Timestamps
    detected_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    recovery_started_at = Column(DateTime(timezone=True))
    recovery_completed_at = Column(DateTime(timezone=True))

    # Foreign keys
    detected_by_id = Column(Integer, ForeignKey("users.id"))

    # Relationships
    detected_by = relationship("User", back_populates="disaster_events")
    recovery_operations = relationship("RecoveryOperation", back_populates="disaster_event")

    # Indexes
    __table_args__ = (
        Index("ix_disaster_events_type_severity", "disaster_type", "severity"),
        Index("ix_disaster_events_detected_at", "detected_at"),
    )


class BackupSchedule(Base):
    """Backup schedule configuration."""
    __tablename__ = "backup_schedules"

    id = Column(Integer, primary_key=True, index=True)
    schedule_id = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    source_pattern = Column(String(255), nullable=False)  # Pattern for sources to backup
    cron_expression = Column(String(100), nullable=False)
    priority = Column(String(20), default="medium")
    enabled = Column(Boolean, default=True)
    max_runtime_minutes = Column(Integer, default=120)
    retry_on_failure = Column(Boolean, default=True)
    retry_count = Column(Integer, default=3)

    # Schedule metadata
    last_run_at = Column(DateTime(timezone=True))
    next_run_at = Column(DateTime(timezone=True))
    last_status = Column(String(20))  # success, failed, skipped
    consecutive_failures = Column(Integer, default=0)

    # Configuration
    backup_type = Column(String(20), default="incremental")
    compression_enabled = Column(Boolean, default=True)
    encryption_enabled = Column(Boolean, default=True)
    verify_after_backup = Column(Boolean, default=True)

    tags = Column(JSON, default=list)

    # Timestamps
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Foreign keys
    policy_id = Column(Integer, ForeignKey("backup_policies.id"))
    created_by_id = Column(Integer, ForeignKey("users.id"))

    # Relationships
    policy = relationship("BackupPolicy")
    created_by = relationship("User", back_populates="backup_schedules")

    # Indexes
    __table_args__ = (
        Index("ix_backup_schedules_enabled_next_run", "enabled", "next_run_at"),
    )


class ModelRecoveryReport(Base):
    """FreeCAD model recovery report."""
    __tablename__ = "model_recovery_reports"

    id = Column(Integer, primary_key=True, index=True)
    report_id = Column(String(100), unique=True, index=True, nullable=False)
    document_id = Column(String(100), index=True, nullable=False)

    # Corruption details
    corruption_type = Column(String(50))  # geometry_invalid, feature_tree_broken, etc.
    corruption_severity = Column(String(20))  # critical, high, medium, low
    affected_features = Column(JSON, default=list)

    # Recovery details
    recovery_strategy = Column(String(50))  # auto_repair, rebuild_features, restore_backup, etc.
    recovery_steps = Column(JSON, default=list)

    # Results
    success = Column(Boolean, nullable=False)
    recovered_features = Column(Integer, default=0)
    lost_features = Column(Integer, default=0)
    validation_passed = Column(Boolean, default=False)

    # Metrics
    duration_seconds = Column(Float)
    errors = Column(JSON, default=list)
    warnings = Column(JSON, default=list)

    # Timestamps
    recovery_timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    # Foreign keys
    recovery_operation_id = Column(Integer, ForeignKey("recovery_operations.id"))
    performed_by_id = Column(Integer, ForeignKey("users.id"))
    job_id = Column(Integer, ForeignKey("jobs.id"))

    # Relationships
    recovery_operation = relationship("RecoveryOperation")
    performed_by = relationship("User", back_populates="model_recovery_reports")
    job = relationship("Job", back_populates="model_recovery_reports")

    # Indexes
    __table_args__ = (
        Index("ix_model_recovery_reports_document_timestamp", "document_id", "recovery_timestamp"),
    )


# Add relationships to User model (would be in user.py)
# User.backup_policies = relationship("BackupPolicy", back_populates="created_by")
# User.backup_snapshots = relationship("BackupSnapshot", back_populates="created_by")
# User.backup_schedules = relationship("BackupSchedule", back_populates="created_by")
# User.recovery_operations = relationship("RecoveryOperation", back_populates="initiated_by")
# User.disaster_events = relationship("DisasterEvent", back_populates="detected_by")
# User.model_recovery_reports = relationship("ModelRecoveryReport", back_populates="performed_by")

# Add relationships to Job model (would be in job.py)
# Job.backup_snapshots = relationship("BackupSnapshot", back_populates="job")
# Job.recovery_operations = relationship("RecoveryOperation", back_populates="job")
# Job.model_recovery_reports = relationship("ModelRecoveryReport", back_populates="job")