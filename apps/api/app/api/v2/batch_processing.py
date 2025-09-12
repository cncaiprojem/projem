"""
Batch Processing API Endpoints

This module provides FastAPI endpoints for batch processing operations including:
- Batch job creation and management
- Quality check execution
- Workflow automation
- Job monitoring and control
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, validator
from sqlalchemy.orm import Session

from ...core.database import get_db
from ...core.logging import get_logger
from ...core.security import get_current_user
from ...models.batch_processing import (
    BatchJob,
    BatchJobStatus,
    BatchOperationType,
    QualityCheck,
    QualityCheckType,
    WorkflowExecution,
    WorkflowStepStatus,
)
from ...models.user import User
from ...services.batch_operations import BatchOperationsService
from ...services.batch_processing_engine import BatchProcessingEngine, process_batch_job
from ...services.workflow_automation import WorkflowAutomation, execute_workflow_async

logger = get_logger(__name__)

router = APIRouter(prefix="/batch", tags=["batch_processing"])


# Pydantic schemas
class BatchJobCreate(BaseModel):
    """Schema for creating a batch job."""
    name: str = Field(..., min_length=1, max_length=255, description="İş adı")
    description: Optional[str] = Field(None, description="İş açıklaması")
    operation_type: BatchOperationType = Field(..., description="İşlem türü")
    input_models: List[int] = Field(..., min_items=1, description="Model ID listesi")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="İş yapılandırması")
    max_retries: Optional[int] = Field(3, ge=0, le=10, description="Maksimum yeniden deneme sayısı")
    retry_delay_seconds: Optional[int] = Field(60, ge=1, le=3600, description="Yeniden deneme gecikmesi")
    
    @validator("input_models")
    def validate_input_models(cls, v):
        if len(v) > 1000:
            raise ValueError("Maximum 1000 models can be processed in a single batch")
        return v


class BatchJobResponse(BaseModel):
    """Response schema for batch job."""
    id: int
    name: str
    description: Optional[str]
    operation_type: str
    status: str
    total_items: int
    processed_items: int
    failed_items: int
    skipped_items: int
    progress_percentage: float
    success_rate: float
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[float]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class QualityCheckCreate(BaseModel):
    """Schema for creating quality checks."""
    model_ids: List[int] = Field(..., min_items=1, description="Model ID listesi")
    check_types: List[QualityCheckType] = Field(..., min_items=1, description="Kalite kontrol türleri")
    auto_fix: Optional[bool] = Field(False, description="Otomatik düzeltme uygula")
    config: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Kontrol yapılandırması")


class QualityCheckResponse(BaseModel):
    """Response schema for quality check."""
    id: int
    model_id: int
    check_type: str
    status: str
    passed: Optional[bool]
    score: Optional[float]
    severity: Optional[str]
    issues_found: int
    issues_fixed: int
    findings: List[Dict[str, Any]]
    recommendations: List[Dict[str, Any]]
    auto_fix_available: bool
    auto_fix_applied: bool
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[float]
    
    class Config:
        from_attributes = True


class WorkflowExecutionCreate(BaseModel):
    """Schema for creating workflow execution."""
    workflow_name: str = Field(..., description="İş akışı adı")
    workflow_version: Optional[str] = Field("1.0", description="İş akışı sürümü")
    template_name: Optional[str] = Field(None, description="Şablon adı")
    custom_steps: Optional[List[Dict[str, Any]]] = Field(None, description="Özel adımlar")
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict, description="İş akışı parametreleri")
    input_models: List[int] = Field(..., min_items=1, description="Model ID listesi")
    
    @validator("custom_steps")
    def validate_steps(cls, v, values):
        if not v and not values.get("template_name"):
            raise ValueError("Either template_name or custom_steps must be provided")
        return v


class WorkflowExecutionResponse(BaseModel):
    """Response schema for workflow execution."""
    id: int
    batch_job_id: int
    workflow_name: str
    workflow_version: Optional[str]
    status: str
    total_steps: int
    completed_steps: int
    failed_steps: int
    current_step: Optional[str]
    progress_percentage: float
    start_time: datetime
    end_time: Optional[datetime]
    duration_seconds: Optional[float]
    error_message: Optional[str]
    error_step: Optional[str]
    
    class Config:
        from_attributes = True


class BatchJobUpdate(BaseModel):
    """Schema for updating batch job."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    retry_delay_seconds: Optional[int] = Field(None, ge=1, le=3600)


# API Endpoints
@router.post("/jobs", response_model=BatchJobResponse, status_code=status.HTTP_201_CREATED)
async def create_batch_job(
    job_data: BatchJobCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> BatchJobResponse:
    """
    Yeni bir toplu işlem işi oluştur.
    
    - **name**: İş adı
    - **operation_type**: İşlem türü (quality_check, mesh_optimization, vb.)
    - **input_models**: İşlenecek model ID'leri
    - **config**: İş yapılandırması
    """
    try:
        # Create batch job
        batch_job = BatchJob(
            user_id=current_user.id,
            name=job_data.name,
            description=job_data.description,
            operation_type=job_data.operation_type,
            input_models=job_data.input_models,
            config=job_data.config,
            max_retries=job_data.max_retries,
            retry_delay_seconds=job_data.retry_delay_seconds,
            total_items=len(job_data.input_models)
        )
        db.add(batch_job)
        db.commit()
        db.refresh(batch_job)
        
        # Schedule async execution
        engine = BatchProcessingEngine(db)
        task_id = engine.schedule_batch_job(batch_job, current_user)
        
        logger.info(f"Created batch job {batch_job.id} with task {task_id} for user {current_user.id}")
        
        return BatchJobResponse.model_validate(batch_job)
        
    except Exception as e:
        logger.error(f"Failed to create batch job: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Toplu işlem işi oluşturulamadı"
        )


@router.get("/jobs", response_model=List[BatchJobResponse])
async def list_batch_jobs(
    skip: int = Query(0, ge=0, description="Atlanacak kayıt sayısı"),
    limit: int = Query(100, ge=1, le=1000, description="Maksimum kayıt sayısı"),
    status: Optional[BatchJobStatus] = Query(None, description="Durum filtresi"),
    operation_type: Optional[BatchOperationType] = Query(None, description="İşlem türü filtresi"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> List[BatchJobResponse]:
    """Kullanıcının toplu işlem işlerini listele."""
    query = db.query(BatchJob).filter(BatchJob.user_id == current_user.id)
    
    if status:
        query = query.filter(BatchJob.status == status)
    
    if operation_type:
        query = query.filter(BatchJob.operation_type == operation_type)
    
    jobs = query.order_by(BatchJob.created_at.desc()).offset(skip).limit(limit).all()
    
    return [BatchJobResponse.model_validate(job) for job in jobs]


@router.get("/jobs/{job_id}", response_model=BatchJobResponse)
async def get_batch_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> BatchJobResponse:
    """Belirli bir toplu işlem işinin detaylarını getir."""
    job = db.query(BatchJob).filter(
        BatchJob.id == job_id,
        BatchJob.user_id == current_user.id
    ).first()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toplu işlem işi bulunamadı"
        )
    
    return BatchJobResponse.model_validate(job)


@router.patch("/jobs/{job_id}", response_model=BatchJobResponse)
async def update_batch_job(
    job_id: int,
    update_data: BatchJobUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> BatchJobResponse:
    """Toplu işlem işini güncelle."""
    job = db.query(BatchJob).filter(
        BatchJob.id == job_id,
        BatchJob.user_id == current_user.id
    ).first()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toplu işlem işi bulunamadı"
        )
    
    if job.status not in [BatchJobStatus.PENDING, BatchJobStatus.PAUSED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sadece bekleyen veya duraklatılmış işler güncellenebilir"
        )
    
    # Update fields
    update_dict = update_data.model_dump(exclude_unset=True)
    for field, value in update_dict.items():
        setattr(job, field, value)
    
    db.commit()
    db.refresh(job)
    
    return BatchJobResponse.model_validate(job)


@router.post("/jobs/{job_id}/cancel", response_model=Dict[str, str])
async def cancel_batch_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """Toplu işlem işini iptal et."""
    job = db.query(BatchJob).filter(
        BatchJob.id == job_id,
        BatchJob.user_id == current_user.id
    ).first()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toplu işlem işi bulunamadı"
        )
    
    if job.status in [BatchJobStatus.COMPLETED, BatchJobStatus.CANCELLED]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="İş zaten tamamlandı veya iptal edildi"
        )
    
    engine = BatchProcessingEngine(db)
    success = engine.cancel_batch_job(job)
    
    if success:
        return {"message": "İş başarıyla iptal edildi", "job_id": str(job_id)}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="İş iptal edilemedi"
        )


@router.post("/jobs/{job_id}/pause", response_model=Dict[str, str])
async def pause_batch_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """Toplu işlem işini duraklat."""
    job = db.query(BatchJob).filter(
        BatchJob.id == job_id,
        BatchJob.user_id == current_user.id
    ).first()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toplu işlem işi bulunamadı"
        )
    
    engine = BatchProcessingEngine(db)
    success = engine.pause_batch_job(job)
    
    if success:
        return {"message": "İş başarıyla duraklatıldı", "job_id": str(job_id)}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="İş duraklatılamadı"
        )


@router.post("/jobs/{job_id}/resume", response_model=Dict[str, str])
async def resume_batch_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """Duraklatılmış toplu işlem işini devam ettir."""
    job = db.query(BatchJob).filter(
        BatchJob.id == job_id,
        BatchJob.user_id == current_user.id
    ).first()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toplu işlem işi bulunamadı"
        )
    
    engine = BatchProcessingEngine(db)
    task_id = engine.resume_batch_job(job, current_user)
    
    if task_id:
        return {"message": "İş başarıyla devam ettirildi", "job_id": str(job_id), "task_id": task_id}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="İş devam ettirilemedi"
        )


@router.post("/quality-checks", response_model=BatchJobResponse, status_code=status.HTTP_201_CREATED)
async def create_quality_checks(
    check_data: QualityCheckCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> BatchJobResponse:
    """Modeller için kalite kontrolleri başlat."""
    try:
        # Create batch job for quality checks
        batch_job = BatchJob(
            user_id=current_user.id,
            name=f"Kalite Kontrolleri - {datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            description=f"{len(check_data.model_ids)} model için {len(check_data.check_types)} kontrol türü",
            operation_type=BatchOperationType.QUALITY_CHECK,
            input_models=check_data.model_ids,
            config={
                "check_types": check_data.check_types,
                "auto_fix": check_data.auto_fix,
                **check_data.config
            },
            total_items=len(check_data.model_ids)
        )
        db.add(batch_job)
        db.commit()
        db.refresh(batch_job)
        
        # Schedule execution
        engine = BatchProcessingEngine(db)
        task_id = engine.schedule_batch_job(batch_job, current_user)
        
        logger.info(f"Created quality check job {batch_job.id} with task {task_id}")
        
        return BatchJobResponse.model_validate(batch_job)
        
    except Exception as e:
        logger.error(f"Failed to create quality checks: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Kalite kontrolleri başlatılamadı"
        )


@router.get("/quality-checks/{job_id}/results", response_model=List[QualityCheckResponse])
async def get_quality_check_results(
    job_id: int,
    model_id: Optional[int] = Query(None, description="Model ID filtresi"),
    check_type: Optional[QualityCheckType] = Query(None, description="Kontrol türü filtresi"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> List[QualityCheckResponse]:
    """Kalite kontrol sonuçlarını getir."""
    # Verify job ownership
    job = db.query(BatchJob).filter(
        BatchJob.id == job_id,
        BatchJob.user_id == current_user.id
    ).first()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toplu işlem işi bulunamadı"
        )
    
    query = db.query(QualityCheck).filter(QualityCheck.batch_job_id == job_id)
    
    if model_id:
        query = query.filter(QualityCheck.model_id == model_id)
    
    if check_type:
        query = query.filter(QualityCheck.check_type == check_type)
    
    checks = query.all()
    
    return [QualityCheckResponse.model_validate(check) for check in checks]


@router.post("/workflows", response_model=WorkflowExecutionResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow_execution(
    workflow_data: WorkflowExecutionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> WorkflowExecutionResponse:
    """Yeni bir iş akışı yürütmesi başlat."""
    try:
        # Create batch job for workflow
        batch_job = BatchJob(
            user_id=current_user.id,
            name=f"İş Akışı - {workflow_data.workflow_name}",
            description=f"İş akışı yürütmesi: {workflow_data.workflow_name}",
            operation_type=BatchOperationType.BATCH_EXPORT,  # Generic type for workflows
            input_models=workflow_data.input_models,
            config=workflow_data.parameters,
            total_items=len(workflow_data.input_models)
        )
        db.add(batch_job)
        db.commit()
        db.refresh(batch_job)
        
        # Create workflow execution
        workflow_execution = WorkflowExecution(
            batch_job_id=batch_job.id,
            workflow_name=workflow_data.workflow_name,
            workflow_version=workflow_data.workflow_version,
            parameters=workflow_data.parameters,
            config={
                "template_name": workflow_data.template_name,
                "custom_steps": workflow_data.custom_steps
            }
        )
        db.add(workflow_execution)
        db.commit()
        db.refresh(workflow_execution)
        
        # Schedule async execution
        task = execute_workflow_async.apply_async(
            kwargs={
                "workflow_execution_id": workflow_execution.id,
                "batch_job_id": batch_job.id,
                "user_id": current_user.id,
                "template_name": workflow_data.template_name,
                "custom_steps": workflow_data.custom_steps
            },
            queue="default",
            routing_key="jobs.workflow"
        )
        
        # Store task ID
        workflow_execution.config["celery_task_id"] = task.id
        db.commit()
        
        logger.info(f"Created workflow execution {workflow_execution.id} with task {task.id}")
        
        return WorkflowExecutionResponse.model_validate(workflow_execution)
        
    except Exception as e:
        logger.error(f"Failed to create workflow execution: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="İş akışı yürütmesi başlatılamadı"
        )


@router.get("/workflows/{execution_id}", response_model=WorkflowExecutionResponse)
async def get_workflow_execution(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> WorkflowExecutionResponse:
    """İş akışı yürütme detaylarını getir."""
    execution = db.query(WorkflowExecution).join(BatchJob).filter(
        WorkflowExecution.id == execution_id,
        BatchJob.user_id == current_user.id
    ).first()
    
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="İş akışı yürütmesi bulunamadı"
        )
    
    return WorkflowExecutionResponse.model_validate(execution)


@router.get("/workflows/{execution_id}/steps", response_model=List[Dict[str, Any]])
async def get_workflow_steps(
    execution_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """İş akışı adımlarını getir."""
    execution = db.query(WorkflowExecution).join(BatchJob).filter(
        WorkflowExecution.id == execution_id,
        BatchJob.user_id == current_user.id
    ).first()
    
    if not execution:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="İş akışı yürütmesi bulunamadı"
        )
    
    return execution.steps


@router.get("/templates", response_model=List[Dict[str, Any]])
async def list_workflow_templates(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    """Kullanılabilir iş akışı şablonlarını listele."""
    automation = WorkflowAutomation(db)
    
    templates = []
    for name, template in automation.templates.items():
        templates.append({
            "name": template.name,
            "version": template.version,
            "description": template.description,
            "parameters": template.parameters,
            "steps_count": len(template.steps)
        })
    
    return templates


@router.post("/recover-failed", response_model=Dict[str, Any])
async def recover_failed_jobs(
    time_window_hours: int = Query(24, ge=1, le=168, description="Zaman penceresi (saat)"),
    max_jobs: int = Query(10, ge=1, le=100, description="Maksimum iş sayısı"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, Any]:
    """Başarısız işleri kurtar ve yeniden dene."""
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu işlem için yönetici yetkisi gerekli"
        )
    
    engine = BatchProcessingEngine(db)
    
    # Run async recovery
    import asyncio
    recovered_jobs = asyncio.run(
        engine.recover_failed_jobs(time_window_hours, max_jobs)
    )
    
    return {
        "recovered_count": len(recovered_jobs),
        "recovered_jobs": [
            {
                "id": job.id,
                "name": job.name,
                "retry_count": job.retry_count
            }
            for job in recovered_jobs
        ]
    }