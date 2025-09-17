"""
Task 7.26: API Endpoints for Backup and Recovery

FastAPI endpoints for backup, recovery, and disaster management operations.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import func

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy.orm import Session

from ....core import security
from ....db.deps import get_db
from ....models import User
from ....models.backup_recovery import (
    BackupPolicy as BackupPolicyModel,
    BackupSnapshot as BackupSnapshotModel,
    RecoveryOperation as RecoveryOperationModel,
    DisasterEvent as DisasterEventModel,
    BackupSchedule as BackupScheduleModel,
    ModelRecoveryReport as ModelRecoveryReportModel
)
from ....schemas.backup_recovery import (
    BackupPolicyCreate,
    BackupPolicyUpdate,
    BackupPolicyResponse,
    BackupSnapshotCreate,
    BackupSnapshotResponse,
    RecoveryOperationCreate,
    RecoveryOperationUpdate,
    RecoveryOperationResponse,
    DisasterEventCreate,
    DisasterEventUpdate,
    DisasterEventResponse,
    BackupScheduleCreate,
    BackupScheduleUpdate,
    BackupScheduleResponse,
    ModelRecoveryRequest,
    ModelRecoveryReportResponse,
    BatchBackupRequest,
    BatchRecoveryRequest,
    BackupStatusResponse,
    RecoveryMetricsResponse,
    HealthCheckResponse
)
from ....services.backup_strategy import backup_strategy
from ....services.incremental_backup import incremental_manager, BackupType
from ....services.disaster_recovery import dr_orchestrator, DisasterType, RecoveryPriority
from ....services.point_in_time_recovery import pitr_manager, RecoveryMode, RecoveryRequest
from ....services.model_recovery_service import model_recovery_service
from ....core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/backup-recovery", tags=["backup-recovery"])


# Backup Policy Endpoints
@router.post("/policies", response_model=BackupPolicyResponse, status_code=status.HTTP_201_CREATED)
async def create_backup_policy(
    policy: BackupPolicyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    Create a new backup retention policy.
    """
    # Generate unique policy ID using UUID for safety
    policy_id = f"policy_{uuid.uuid4().hex}"

    db_policy = BackupPolicyModel(
        policy_id=policy_id,
        name=policy.name,
        type=policy.type,
        retention_days=policy.retention_days,
        retention_versions=policy.retention_versions,
        legal_hold_until=policy.legal_hold_until,
        compliance_mode=policy.compliance_mode,
        priority=policy.priority,
        tags=policy.tags,
        created_by_id=current_user.id
    )

    db.add(db_policy)
    db.commit()
    db.refresh(db_policy)

    logger.info(f"Yedekleme politikası oluşturuldu: {policy_id}")

    return db_policy


@router.get("/policies", response_model=List[BackupPolicyResponse])
async def list_backup_policies(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    List backup retention policies.
    """
    policies = db.query(BackupPolicyModel).offset(skip).limit(limit).all()
    return policies


@router.get("/policies/{policy_id}", response_model=BackupPolicyResponse)
async def get_backup_policy(
    policy_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    Get backup policy by ID.
    """
    policy = db.query(BackupPolicyModel).filter(
        BackupPolicyModel.policy_id == policy_id
    ).first()

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Yedekleme politikası bulunamadı"
        )

    return policy


@router.patch("/policies/{policy_id}", response_model=BackupPolicyResponse)
async def update_backup_policy(
    policy_id: str,
    policy_update: BackupPolicyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_superuser)
) -> Any:
    """
    Update backup policy (admin only).
    """
    policy = db.query(BackupPolicyModel).filter(
        BackupPolicyModel.policy_id == policy_id
    ).first()

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Yedekleme politikası bulunamadı"
        )

    update_data = policy_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(policy, field, value)

    db.commit()
    db.refresh(policy)

    logger.info(f"Yedekleme politikası güncellendi: {policy_id}")

    return policy


# Backup Snapshot Endpoints
@router.post("/backups", response_model=BackupSnapshotResponse, status_code=status.HTTP_201_CREATED)
async def create_backup(
    backup_request: BackupSnapshotCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    Create a new backup snapshot.
    """
    # This would typically fetch the actual data to backup
    # For now, create mock data
    data = b"mock_model_data"

    # Convert string policy_id to database ID if provided
    db_policy_id = None
    if backup_request.policy_id:
        policy = db.query(BackupPolicyModel).filter(
            BackupPolicyModel.policy_id == backup_request.policy_id
        ).first()
        if policy:
            db_policy_id = policy.id

    # Create backup using backup strategy
    metadata = await backup_strategy.create_backup(
        data=data,
        source_id=backup_request.source_id,
        backup_type=backup_request.backup_type,
        retention_policy_id=backup_request.policy_id
    )

    # Store in database
    db_backup = BackupSnapshotModel(
        backup_id=metadata.backup_id,
        source_id=metadata.source_id,
        backup_type=metadata.backup_type,
        size_bytes=metadata.size_bytes,
        compressed_size_bytes=metadata.compressed_size_bytes,
        checksum=metadata.checksum,
        encryption_method=metadata.encryption_method.value,
        compression_algorithm=metadata.compression_algorithm.value,
        storage_tier=metadata.storage_tier.value,
        storage_path=metadata.storage_path,
        policy_id=db_policy_id,
        created_by_id=current_user.id,
        metadata=backup_request.metadata
    )

    db.add(db_backup)
    db.commit()
    db.refresh(db_backup)

    # Schedule verification if requested
    if backup_request.verify_after_backup:
        background_tasks.add_task(verify_backup_task, db_backup.id)

    logger.info(f"Yedekleme oluşturuldu: {metadata.backup_id}")

    return db_backup


@router.get("/backups", response_model=List[BackupSnapshotResponse])
async def list_backups(
    source_id: Optional[str] = Query(None),
    backup_type: Optional[str] = Query(None),
    storage_tier: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    List backup snapshots with optional filters.
    """
    query = db.query(BackupSnapshotModel)

    if source_id:
        query = query.filter(BackupSnapshotModel.source_id == source_id)
    if backup_type:
        query = query.filter(BackupSnapshotModel.backup_type == backup_type)
    if storage_tier:
        query = query.filter(BackupSnapshotModel.storage_tier == storage_tier)

    backups = query.order_by(BackupSnapshotModel.created_at.desc()).offset(skip).limit(limit).all()
    return backups


@router.delete("/backups/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(
    backup_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_superuser)
) -> None:
    """
    Delete backup snapshot (admin only).
    """
    backup = db.query(BackupSnapshotModel).filter(
        BackupSnapshotModel.backup_id == backup_id
    ).first()

    if not backup:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Yedekleme bulunamadı"
        )

    # Delete from database first for atomicity
    db.delete(backup)
    db.commit()

    # Then attempt to delete from storage (non-critical)
    try:
        await backup_strategy.storage.delete(backup.storage_path)
    except Exception as e:
        logger.warning(f"Storage silme başarısız ancak DB kaydı silindi: {backup_id}", exc_info=True)

    logger.info(f"Yedekleme silindi: {backup_id}")


# Recovery Operation Endpoints
@router.post("/recovery", response_model=RecoveryOperationResponse, status_code=status.HTTP_202_ACCEPTED)
async def initiate_recovery(
    recovery_request: RecoveryOperationCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    Initiate recovery operation.
    """
    # Generate unique operation ID using UUID
    operation_id = f"recovery_{uuid.uuid4().hex}"

    # Convert string backup_id to database ID if provided
    db_backup_id = None
    if recovery_request.backup_id:
        backup = db.query(BackupSnapshotModel).filter(
            BackupSnapshotModel.backup_id == recovery_request.backup_id
        ).first()
        if backup:
            db_backup_id = backup.id

    # Create recovery operation record
    db_operation = RecoveryOperationModel(
        operation_id=operation_id,
        recovery_type=recovery_request.recovery_type,
        source_id=recovery_request.source_id,
        recovery_mode=recovery_request.recovery_mode,
        target_timestamp=recovery_request.target_timestamp,
        target_transaction_id=recovery_request.target_transaction_id,
        backup_id=db_backup_id,
        status="pending",
        initiated_by_id=current_user.id,
        created_at=datetime.now(timezone.utc)
    )

    db.add(db_operation)
    db.commit()
    db.refresh(db_operation)

    # Start recovery in background
    background_tasks.add_task(
        execute_recovery_task,
        db_operation.id,
        recovery_request
    )

    logger.info(f"Kurtarma işlemi başlatıldı: {operation_id}")

    return db_operation


@router.get("/recovery/{operation_id}", response_model=RecoveryOperationResponse)
async def get_recovery_status(
    operation_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    Get recovery operation status.
    """
    operation = db.query(RecoveryOperationModel).filter(
        RecoveryOperationModel.operation_id == operation_id
    ).first()

    if not operation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kurtarma işlemi bulunamadı"
        )

    return operation


# Disaster Recovery Endpoints
@router.post("/disasters", response_model=DisasterEventResponse, status_code=status.HTTP_201_CREATED)
async def report_disaster(
    disaster: DisasterEventCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    Report a disaster event.
    """
    # Validate and convert disaster type with error handling
    try:
        disaster_type_enum = DisasterType(disaster.disaster_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Geçersiz felaket türü: {disaster.disaster_type}"
        )

    # Detect disaster
    event = await dr_orchestrator.detect_disaster(
        disaster_type=disaster_type_enum,
        description=disaster.description
    )

    # Store in database
    db_event = DisasterEventModel(
        event_id=event.event_id,
        disaster_type=event.disaster_type.value,
        severity=event.severity.value,
        description=event.description,
        impacted_components=event.impacted_components,
        estimated_downtime_minutes=disaster.estimated_downtime_minutes,
        recovery_state=event.recovery_state.value,
        detected_by_id=current_user.id
    )

    db.add(db_event)
    db.commit()
    db.refresh(db_event)

    # Auto-recover if requested
    if disaster.auto_recover:
        background_tasks.add_task(
            auto_recover_disaster_task,
            db_event.id
        )

    logger.warning(f"Felaket rapor edildi: {event.event_id}")

    return db_event


@router.get("/disasters", response_model=List[DisasterEventResponse])
async def list_disaster_events(
    disaster_type: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    recovery_state: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    List disaster events with optional filters.
    """
    query = db.query(DisasterEventModel)

    if disaster_type:
        query = query.filter(DisasterEventModel.disaster_type == disaster_type)
    if severity:
        query = query.filter(DisasterEventModel.severity == severity)
    if recovery_state:
        query = query.filter(DisasterEventModel.recovery_state == recovery_state)

    events = query.order_by(DisasterEventModel.detected_at.desc()).offset(skip).limit(limit).all()
    return events


# Model Recovery Endpoints
@router.post("/model-recovery", response_model=ModelRecoveryReportResponse)
async def recover_model(
    recovery_request: ModelRecoveryRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    Recover corrupted FreeCAD model.
    """
    # Execute model recovery
    report = await model_recovery_service.recover_model(
        document_id=recovery_request.document_id,
        strategy=recovery_request.recovery_strategy,
        backup_id=recovery_request.backup_id
    )

    # Store report in database
    db_report = ModelRecoveryReportModel(
        report_id=report.report_id,
        document_id=report.document_id,
        corruption_type=report.corruption.corruption_type.value if report.corruption else None,
        corruption_severity=report.corruption.severity if report.corruption else None,
        affected_features=report.corruption.affected_features if report.corruption else [],
        recovery_strategy=report.plan.strategy.value if report.plan else None,
        recovery_steps=[step.model_dump() for step in report.plan.steps] if report.plan else [],
        success=report.success,
        recovered_features=report.recovered_features,
        lost_features=report.lost_features,
        validation_passed=report.validation_passed,
        duration_seconds=report.duration_seconds,
        errors=report.errors,
        warnings=report.warnings,
        performed_by_id=current_user.id
    )

    db.add(db_report)
    db.commit()
    db.refresh(db_report)

    logger.info(f"Model kurtarma tamamlandı: {report.report_id}")

    return db_report


# Batch Operations
@router.post("/batch/backup", status_code=status.HTTP_202_ACCEPTED)
async def batch_backup(
    batch_request: BatchBackupRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Dict[str, Any]:
    """
    Create backups for multiple sources.
    """
    # Generate unique task ID using UUID
    task_id = f"batch_backup_{uuid.uuid4().hex}"

    # Start batch backup in background
    background_tasks.add_task(
        batch_backup_task,
        task_id,
        batch_request,
        current_user.id
    )

    return {
        "task_id": task_id,
        "source_count": len(batch_request.source_ids),
        "status": "başlatıldı"
    }


@router.post("/batch/recovery", status_code=status.HTTP_202_ACCEPTED)
async def batch_recovery(
    batch_request: BatchRecoveryRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Dict[str, Any]:
    """
    Recover multiple sources.
    """
    # Generate unique task ID using UUID
    task_id = f"batch_recovery_{uuid.uuid4().hex}"

    # Start batch recovery in background
    background_tasks.add_task(
        batch_recovery_task,
        task_id,
        batch_request,
        current_user.id
    )

    return {
        "task_id": task_id,
        "source_count": len(batch_request.source_ids),
        "status": "başlatıldı"
    }


# Status and Metrics
@router.get("/status", response_model=BackupStatusResponse)
async def get_backup_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    Get backup system status.
    """
    # Get all backup statistics in a single optimized query
    # This reduces database round trips and improves performance
    stats = db.query(
        func.count(BackupSnapshotModel.id).label('total_count'),
        func.sum(BackupSnapshotModel.size_bytes).label('total_size'),
        func.min(BackupSnapshotModel.created_at).label('oldest'),
        func.max(BackupSnapshotModel.created_at).label('newest')
    ).first()

    total_backups = stats.total_count or 0
    total_size = stats.total_size or 0
    oldest_backup = stats.oldest
    newest_backup = stats.newest

    # Initialize all possible values to 0 for consistency
    backups_by_type = {backup_type.value: 0 for backup_type in BackupType}

    # Get backup counts by type using single group_by query
    type_counts = db.query(
        BackupSnapshotModel.backup_type,
        func.count(BackupSnapshotModel.id).label('count')
    ).group_by(BackupSnapshotModel.backup_type).all()

    for backup_type, count in type_counts:
        if backup_type in backups_by_type:
            backups_by_type[backup_type] = count

    # Initialize all tier values to 0
    tier_options = ["hot", "warm", "cold", "glacier"]
    backups_by_tier = {tier: 0 for tier in tier_options}

    # Get backup counts by tier using single group_by query
    tier_counts = db.query(
        BackupSnapshotModel.storage_tier,
        func.count(BackupSnapshotModel.id).label('count')
    ).group_by(BackupSnapshotModel.storage_tier).all()

    for tier, count in tier_counts:
        if tier in backups_by_tier:
            backups_by_tier[tier] = count

    # Already retrieved oldest and newest in the combined query above
    # No need for separate queries

    # Get deduplication stats from incremental manager
    stats = incremental_manager.get_stats()

    return BackupStatusResponse(
        total_backups=total_backups,
        total_size_bytes=total_size,
        backups_by_type=backups_by_type,
        backups_by_tier=backups_by_tier,
        oldest_backup=oldest_backup,
        newest_backup=newest_backup,
        deduplication_ratio=stats.get("chunk_stats", {}).get("dedup_ratio", 1.0),
        compression_ratio=0.5  # Would calculate actual ratio
    )


@router.get("/metrics", response_model=RecoveryMetricsResponse)
async def get_recovery_metrics(
    db: Session = Depends(get_db),
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    Get recovery system metrics.
    """
    # Get metrics from DR orchestrator
    metrics = dr_orchestrator.get_metrics()

    # Get recent events
    recent_events = db.query(DisasterEventModel).order_by(
        DisasterEventModel.detected_at.desc()
    ).limit(10).all()

    return RecoveryMetricsResponse(
        total_recoveries=metrics.total_events,
        successful_recoveries=metrics.successful_recoveries,
        failed_recoveries=metrics.failed_recoveries,
        average_recovery_time_minutes=metrics.average_recovery_time_minutes,
        rto_compliance_rate=metrics.rto_compliance_rate,
        rpo_compliance_rate=metrics.rpo_compliance_rate,
        mttr=metrics.mttr,
        mtbf=metrics.mtbf,
        recent_events=[{
            "event_id": e.event_id,
            "type": e.disaster_type,
            "severity": e.severity,
            "detected_at": e.detected_at.isoformat()
        } for e in recent_events]
    )


@router.get("/health", response_model=List[HealthCheckResponse])
async def get_health_status(
    current_user: User = Depends(security.get_current_active_user)
) -> Any:
    """
    Get health status of backup/recovery components.
    """
    health_checks = []

    # Check each component
    for check_id, check in dr_orchestrator.health_monitor.health_checks.items():
        status = dr_orchestrator.health_monitor.health_status.get(check_id, "unknown")

        health_checks.append(HealthCheckResponse(
            component=check.component,
            status=status,
            last_check=dr_orchestrator.health_monitor.last_check_timestamps.get(
                check_id, None  # Return None if component has never been checked
            ),
            failure_count=dr_orchestrator.health_monitor.failure_counts.get(check_id, 0),
            success_count=dr_orchestrator.health_monitor.success_counts.get(check_id, 0),
            details={"check_type": check.check_type, "critical": check.critical}
        ))

    return health_checks


# Background tasks
async def verify_backup_task(backup_id: int):
    """Background task to verify backup."""
    # Would implement backup verification
    logger.info(f"Yedekleme doğrulanıyor: {backup_id}")


async def execute_recovery_task(operation_id: int, recovery_request: RecoveryOperationCreate):
    """Background task to execute recovery."""
    # Would implement recovery execution
    logger.info(f"Kurtarma yürütülüyor: {operation_id}")


async def auto_recover_disaster_task(event_id: int):
    """Background task for automatic disaster recovery."""
    # Would implement auto-recovery
    logger.info(f"Otomatik kurtarma başlatılıyor: {event_id}")


async def batch_backup_task(task_id: str, batch_request: BatchBackupRequest, user_id: int):
    """Background task for batch backup."""
    # Would implement batch backup
    logger.info(f"Toplu yedekleme yürütülüyor: {task_id}")


async def batch_recovery_task(task_id: str, batch_request: BatchRecoveryRequest, user_id: int):
    """Background task for batch recovery."""
    # Would implement batch recovery
    logger.info(f"Toplu kurtarma yürütülüyor: {task_id}")