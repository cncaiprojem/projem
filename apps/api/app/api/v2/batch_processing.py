"""
API endpoints for Batch Processing and Automation Framework (Task 7.23)

Provides REST API for:
- Batch job submission and monitoring
- Workflow definition and execution
- Scheduled job management
- Progress tracking and results
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_, func
from pydantic import BaseModel, Field

from ...core.dependencies import get_current_user, get_db
from ...core.logging import get_logger
from ...core.telemetry import create_span
from ...models import User
from ...models.batch_processing import (
    BatchJob,
    BatchJobItem,
    WorkflowDefinition,
    WorkflowExecution,
    ScheduledJob,
    ScheduledJobExecution
)
from ...services.batch_processing_engine import (
    BatchItem,
    BatchOptions,
    BatchProcessingEngine,
    BatchStatus,
    ProcessingStrategy
)
from ...services.workflow_automation import (
    Workflow,
    WorkflowEngine,
    WorkflowStep,
    ExecutionOptions,
    WorkflowStatus
)
from ...services.scheduled_operations import (
    ScheduledOperations,
    ScheduledJobConfig,
    JobTriggerType
)
from ...services.batch_operations import (
    BatchOperations,
    ParameterSet,
    QualityCheck,
    QualityCheckType
)

logger = get_logger(__name__)

router = APIRouter(prefix="/batch", tags=["batch-processing"])


# Request/Response models
class BatchJobSubmit(BaseModel):
    """Request model for batch job submission."""
    name: str = Field(description="İş adı")
    description: Optional[str] = Field(default=None, description="Açıklama")
    operation: str = Field(description="İşlem tipi (convert, optimize, quality_check, etc.)")
    items: List[Dict[str, Any]] = Field(description="İşlenecek öğeler")
    options: Optional[BatchOptions] = Field(default=None, description="İşleme seçenekleri")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Ek bilgiler")


class BatchJobResponse(BaseModel):
    """Response model for batch job."""
    id: int
    batch_id: str
    name: str
    status: str
    total_items: int
    processed_items: int
    successful_items: int
    failed_items: int
    progress_percent: float
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    duration_ms: Optional[float]
    results: Optional[List[Any]] = None
    errors: Optional[Dict[str, str]] = None


class BatchProgressResponse(BaseModel):
    """Response model for batch progress."""
    batch_id: str
    status: str
    total: int
    processed: int
    successful: int
    failed: int
    skipped: int
    progress_percent: float
    current_item: Optional[str]
    estimated_time_remaining: Optional[float]


class WorkflowSubmit(BaseModel):
    """Request model for workflow submission."""
    name: str = Field(description="İş akışı adı")
    description: Optional[str] = Field(default=None, description="Açıklama")
    steps: List[Dict[str, Any]] = Field(description="İş akışı adımları")
    entry_point: Optional[str] = Field(default=None, description="Başlangıç adımı")
    global_timeout: Optional[int] = Field(default=None, ge=60, le=86400, description="Toplam timeout")


class WorkflowExecuteRequest(BaseModel):
    """Request model for workflow execution."""
    workflow_id: str = Field(description="İş akışı ID")
    input_data: Dict[str, Any] = Field(default_factory=dict, description="Giriş verileri")
    options: Optional[ExecutionOptions] = Field(default=None, description="Yürütme seçenekleri")


class WorkflowExecutionResponse(BaseModel):
    """Response model for workflow execution."""
    id: int
    execution_id: str
    workflow_id: str
    status: str
    current_step: Optional[str]
    start_time: datetime
    end_time: Optional[datetime]
    duration_ms: Optional[float]
    error: Optional[str]
    step_results: Optional[Dict[str, Any]]


class ScheduledJobSubmit(BaseModel):
    """Request model for scheduled job submission."""
    name: str = Field(description="İş adı")
    description: Optional[str] = Field(default=None, description="Açıklama")
    function: str = Field(description="Çalıştırılacak fonksiyon")
    trigger_type: JobTriggerType = Field(description="Tetikleyici tipi")
    trigger_args: Dict[str, Any] = Field(description="Tetikleyici parametreleri")
    args: Optional[List[Any]] = Field(default=None, description="Fonksiyon argümanları")
    kwargs: Optional[Dict[str, Any]] = Field(default=None, description="Fonksiyon keyword argümanları")
    enabled: bool = Field(default=True, description="İş etkin mi")


class ScheduledJobResponse(BaseModel):
    """Response model for scheduled job."""
    id: int
    job_id: str
    name: str
    trigger_type: str
    enabled: bool
    next_run_time: Optional[datetime]
    last_run_time: Optional[datetime]


# Initialize services
batch_engine = BatchProcessingEngine()
workflow_engine = WorkflowEngine()
# Scheduler will be initialized in lifespan events to avoid startup at module level
scheduler: Optional[ScheduledOperations] = None
batch_operations = BatchOperations()


def get_scheduler() -> ScheduledOperations:
    """Get or initialize the scheduler."""
    global scheduler
    if scheduler is None:
        scheduler = ScheduledOperations()
        if not scheduler.is_running():
            scheduler.start()
    return scheduler


@router.post("/jobs", response_model=BatchJobResponse, status_code=status.HTTP_201_CREATED)
async def submit_batch_job(
    request: BatchJobSubmit,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> BatchJobResponse:
    """
    Submit a new batch processing job.
    
    Toplu işlem işi gönder.
    """
    with create_span("submit_batch_job") as span:
        span.set_attribute("operation", request.operation)
        span.set_attribute("item_count", len(request.items))
        
        try:
            # Create batch job record
            batch_id = str(uuid.uuid4())
            batch_job = BatchJob(
                batch_id=batch_id,
                name=request.name,
                description=request.description,
                operation=request.operation,
                status=BatchStatus.CREATED,
                total_items=len(request.items),
                strategy=request.options.strategy if request.options else ProcessingStrategy.ADAPTIVE,
                max_workers=request.options.max_workers if request.options else None,
                chunk_size=request.options.chunk_size if request.options else 10,
                max_retries=request.options.max_retries if request.options else 3,
                continue_on_error=request.options.continue_on_error if request.options else True,
                user_id=current_user.id,
                metadata_=request.metadata or {}
            )
            
            db.add(batch_job)
            await db.commit()
            await db.refresh(batch_job)
            
            # Create batch items
            batch_items = []
            for item_data in request.items:
                batch_item = BatchItem(data=item_data)
                batch_items.append(batch_item)
            
            # Schedule background processing
            background_tasks.add_task(
                process_batch_job,
                batch_job.id,
                batch_items,
                request.operation,
                request.options
            )
            
            logger.info(f"Toplu işlem gönderildi: {batch_id}, {len(request.items)} öğe")
            
            return BatchJobResponse(
                id=batch_job.id,
                batch_id=batch_job.batch_id,
                name=batch_job.name,
                status=batch_job.status.value,
                total_items=batch_job.total_items,
                processed_items=0,
                successful_items=0,
                failed_items=0,
                progress_percent=0.0,
                start_time=None,
                end_time=None,
                duration_ms=None
            )
            
        except Exception as e:
            logger.error(f"Toplu işlem gönderme hatası: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Toplu işlem gönderilemedi: {str(e)}"
            )


@router.get("/jobs/{batch_id}", response_model=BatchJobResponse)
async def get_batch_job(
    batch_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> BatchJobResponse:
    """
    Get batch job details.
    
    Toplu işlem detaylarını getir.
    """
    query = select(BatchJob).where(
        and_(
            BatchJob.batch_id == batch_id,
            or_(
                BatchJob.user_id == current_user.id,
                current_user.role == "admin"
            )
        )
    )
    
    result = await db.execute(query)
    batch_job = result.scalar_one_or_none()
    
    if not batch_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Toplu işlem bulunamadı"
        )
    
    return BatchJobResponse(
        id=batch_job.id,
        batch_id=batch_job.batch_id,
        name=batch_job.name,
        status=batch_job.status.value,
        total_items=batch_job.total_items,
        processed_items=batch_job.processed_items,
        successful_items=batch_job.successful_items,
        failed_items=batch_job.failed_items,
        progress_percent=batch_job.progress_percent,
        start_time=batch_job.start_time,
        end_time=batch_job.end_time,
        duration_ms=batch_job.duration_ms,
        results=batch_job.results if batch_job.is_complete else None,
        errors=batch_job.errors if batch_job.errors else None
    )


@router.get("/jobs/{batch_id}/progress", response_model=BatchProgressResponse)
async def get_batch_progress(
    batch_id: str,
    current_user: User = Depends(get_current_user)
) -> BatchProgressResponse:
    """
    Get real-time batch job progress.
    
    Toplu işlem ilerlemesini getir.
    """
    progress = await batch_engine.progress_tracker.get_progress(batch_id)
    
    if not progress:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="İlerleme bilgisi bulunamadı"
        )
    
    # Calculate estimated time
    estimated_time = None
    if progress.get("processed", 0) > 0:
        elapsed = (datetime.now(UTC) - datetime.fromisoformat(progress["start_time"])).total_seconds()
        rate = progress["processed"] / elapsed
        remaining = progress["total"] - progress["processed"]
        estimated_time = remaining / rate if rate > 0 else None
    
    return BatchProgressResponse(
        batch_id=batch_id,
        status=progress.get("status", "unknown"),
        total=progress.get("total", 0),
        processed=progress.get("processed", 0),
        successful=progress.get("successful", 0),
        failed=progress.get("failed", 0),
        skipped=progress.get("skipped", 0),
        progress_percent=(progress.get("processed", 0) / progress.get("total", 1)) * 100,
        current_item=progress.get("current_item"),
        estimated_time_remaining=estimated_time
    )


@router.get("/jobs", response_model=List[BatchJobResponse])
async def list_batch_jobs(
    status: Optional[BatchStatus] = Query(default=None, description="Filter by status"),
    limit: int = Query(default=20, ge=1, le=100, description="Limit"),
    offset: int = Query(default=0, ge=0, description="Offset"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[BatchJobResponse]:
    """
    List batch jobs.
    
    Toplu işlemleri listele.
    """
    query = select(BatchJob).where(
        or_(
            BatchJob.user_id == current_user.id,
            current_user.role == "admin"
        )
    )
    
    if status:
        query = query.where(BatchJob.status == status)
    
    query = query.order_by(BatchJob.created_at.desc()).limit(limit).offset(offset)
    
    result = await db.execute(query)
    batch_jobs = result.scalars().all()
    
    return [
        BatchJobResponse(
            id=job.id,
            batch_id=job.batch_id,
            name=job.name,
            status=job.status.value,
            total_items=job.total_items,
            processed_items=job.processed_items,
            successful_items=job.successful_items,
            failed_items=job.failed_items,
            progress_percent=job.progress_percent,
            start_time=job.start_time,
            end_time=job.end_time,
            duration_ms=job.duration_ms
        )
        for job in batch_jobs
    ]


@router.post("/workflows", response_model=Dict[str, str], status_code=status.HTTP_201_CREATED)
async def create_workflow(
    request: WorkflowSubmit,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Create a new workflow definition.
    
    Yeni iş akışı tanımı oluştur.
    """
    with create_span("create_workflow") as span:
        span.set_attribute("workflow_name", request.name)
        
        try:
            # Create workflow object
            workflow = Workflow(
                name=request.name,
                description=request.description,
                steps=[WorkflowStep(**step) for step in request.steps],
                entry_point=request.entry_point,
                global_timeout=request.global_timeout
            )
            
            # Validate and register workflow
            await workflow_engine.define_workflow(workflow)
            
            # Save to database
            workflow_def = WorkflowDefinition(
                workflow_id=workflow.id,
                name=workflow.name,
                description=workflow.description,
                version=workflow.version,
                steps=request.steps,
                entry_point=workflow.entry_point,
                global_timeout=workflow.global_timeout,
                created_by=current_user.id
            )
            
            db.add(workflow_def)
            await db.commit()
            
            logger.info(f"İş akışı oluşturuldu: {workflow.name} ({workflow.id})")
            
            return {
                "workflow_id": workflow.id,
                "message": "İş akışı başarıyla oluşturuldu"
            }
            
        except Exception as e:
            logger.error(f"İş akışı oluşturma hatası: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"İş akışı oluşturulamadı: {str(e)}"
            )


@router.post("/workflows/execute", response_model=WorkflowExecutionResponse, status_code=status.HTTP_201_CREATED)
async def execute_workflow(
    request: WorkflowExecuteRequest,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkflowExecutionResponse:
    """
    Execute a workflow.
    
    İş akışını çalıştır.
    """
    with create_span("execute_workflow") as span:
        span.set_attribute("workflow_id", request.workflow_id)
        
        # Check workflow exists
        query = select(WorkflowDefinition).where(
            WorkflowDefinition.workflow_id == request.workflow_id
        )
        result = await db.execute(query)
        workflow_def = result.scalar_one_or_none()
        
        if not workflow_def:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="İş akışı bulunamadı"
            )
        
        # Create execution record
        execution_id = str(uuid.uuid4())
        workflow_exec = WorkflowExecution(
            execution_id=execution_id,
            workflow_definition_id=workflow_def.id,
            user_id=current_user.id,
            status=WorkflowStatus.CREATED,
            input_data=request.input_data
        )
        
        db.add(workflow_exec)
        await db.commit()
        await db.refresh(workflow_exec)
        
        # Schedule background execution
        background_tasks.add_task(
            execute_workflow_async,
            workflow_exec.id,
            request.workflow_id,
            request.input_data,
            request.options
        )
        
        logger.info(f"İş akışı yürütme başlatıldı: {execution_id}")
        
        return WorkflowExecutionResponse(
            id=workflow_exec.id,
            execution_id=workflow_exec.execution_id,
            workflow_id=request.workflow_id,
            status=workflow_exec.status.value,
            current_step=None,
            start_time=workflow_exec.start_time,
            end_time=None,
            duration_ms=None,
            error=None,
            step_results=None
        )


@router.get("/workflows/executions/{execution_id}", response_model=WorkflowExecutionResponse)
async def get_workflow_execution(
    execution_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> WorkflowExecutionResponse:
    """
    Get workflow execution details.
    
    İş akışı yürütme detaylarını getir.
    """
    query = select(WorkflowExecution).where(
        and_(
            WorkflowExecution.execution_id == execution_id,
            or_(
                WorkflowExecution.user_id == current_user.id,
                current_user.role == "admin"
            )
        )
    )
    
    result = await db.execute(query)
    workflow_exec = result.scalar_one_or_none()
    
    if not workflow_exec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="İş akışı yürütmesi bulunamadı"
        )
    
    # Get workflow ID
    workflow_def = await db.get(WorkflowDefinition, workflow_exec.workflow_definition_id)
    
    return WorkflowExecutionResponse(
        id=workflow_exec.id,
        execution_id=workflow_exec.execution_id,
        workflow_id=workflow_def.workflow_id if workflow_def else "unknown",
        status=workflow_exec.status.value,
        current_step=workflow_exec.current_step,
        start_time=workflow_exec.start_time,
        end_time=workflow_exec.end_time,
        duration_ms=workflow_exec.duration_ms,
        error=workflow_exec.error,
        step_results=workflow_exec.step_results
    )


@router.post("/scheduled", response_model=ScheduledJobResponse, status_code=status.HTTP_201_CREATED)
async def create_scheduled_job(
    request: ScheduledJobSubmit,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> ScheduledJobResponse:
    """
    Create a scheduled job.
    
    Zamanlanmış iş oluştur.
    """
    with create_span("create_scheduled_job") as span:
        span.set_attribute("job_name", request.name)
        span.set_attribute("trigger_type", request.trigger_type.value)
        
        try:
            # Create job config
            job_config = ScheduledJobConfig(
                name=request.name,
                description=request.description,
                trigger_type=request.trigger_type,
                trigger_args=request.trigger_args,
                function=request.function,
                args=request.args or [],
                kwargs=request.kwargs or {},
                enabled=request.enabled
            )
            
            # Schedule job
            job_id = get_scheduler().schedule_job(job_config)
            
            # Save to database
            scheduled_job = ScheduledJob(
                job_id=job_id,
                name=request.name,
                description=request.description,
                function=request.function,
                trigger_type=request.trigger_type,
                trigger_args=request.trigger_args,
                args=request.args or [],
                kwargs=request.kwargs or {},
                enabled=request.enabled,
                created_by=current_user.id
            )
            
            db.add(scheduled_job)
            await db.commit()
            await db.refresh(scheduled_job)
            
            logger.info(f"Zamanlanmış iş oluşturuldu: {request.name} ({job_id})")
            
            return ScheduledJobResponse(
                id=scheduled_job.id,
                job_id=scheduled_job.job_id,
                name=scheduled_job.name,
                trigger_type=scheduled_job.trigger_type.value,
                enabled=scheduled_job.enabled,
                next_run_time=scheduled_job.next_run_time,
                last_run_time=scheduled_job.last_run_time
            )
            
        except Exception as e:
            logger.error(f"Zamanlanmış iş oluşturma hatası: {e}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Zamanlanmış iş oluşturulamadı: {str(e)}"
            )


@router.get("/scheduled", response_model=List[ScheduledJobResponse])
async def list_scheduled_jobs(
    enabled: Optional[bool] = Query(default=None, description="Filter by enabled status"),
    limit: int = Query(default=20, ge=1, le=100, description="Limit"),
    offset: int = Query(default=0, ge=0, description="Offset"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[ScheduledJobResponse]:
    """
    List scheduled jobs.
    
    Zamanlanmış işleri listele.
    """
    query = select(ScheduledJob)
    
    if enabled is not None:
        query = query.where(ScheduledJob.enabled == enabled)
    
    if current_user.role != "admin":
        query = query.where(ScheduledJob.created_by == current_user.id)
    
    query = query.order_by(ScheduledJob.created_at.desc()).limit(limit).offset(offset)
    
    result = await db.execute(query)
    scheduled_jobs = result.scalars().all()
    
    return [
        ScheduledJobResponse(
            id=job.id,
            job_id=job.job_id,
            name=job.name,
            trigger_type=job.trigger_type.value,
            enabled=job.enabled,
            next_run_time=job.next_run_time,
            last_run_time=job.last_run_time
        )
        for job in scheduled_jobs
    ]


@router.delete("/scheduled/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scheduled_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> None:
    """
    Delete a scheduled job.
    
    Zamanlanmış işi sil.
    """
    query = select(ScheduledJob).where(
        and_(
            ScheduledJob.job_id == job_id,
            or_(
                ScheduledJob.created_by == current_user.id,
                current_user.role == "admin"
            )
        )
    )
    
    result = await db.execute(query)
    scheduled_job = result.scalar_one_or_none()
    
    if not scheduled_job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Zamanlanmış iş bulunamadı"
        )
    
    # Remove from scheduler
    get_scheduler().remove_job(job_id)
    
    # Delete from database
    await db.delete(scheduled_job)
    await db.commit()
    
    logger.info(f"Zamanlanmış iş silindi: {job_id}")


# Background task functions
async def process_batch_job(
    batch_job_id: int,
    batch_items: List[BatchItem],
    operation: str,
    options: Optional[BatchOptions]
) -> None:
    """Process batch job in background."""
    # This would be implemented to actually process the batch
    # For now, it's a placeholder
    logger.info(f"Processing batch job {batch_job_id} with {len(batch_items)} items")


async def execute_workflow_async(
    workflow_exec_id: int,
    workflow_id: str,
    input_data: Dict[str, Any],
    options: Optional[ExecutionOptions]
) -> None:
    """Execute workflow in background."""
    # This would be implemented to actually execute the workflow
    # For now, it's a placeholder
    logger.info(f"Executing workflow {workflow_id} (execution {workflow_exec_id})")


# Scheduler is now initialized lazily via get_scheduler() to avoid module-level startup
# This prevents issues with process spawning and ensures proper lifecycle management