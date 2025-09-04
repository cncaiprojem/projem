"""
Ultra-Enterprise Assembly4 API Router for Task 7.8

This router provides comprehensive Assembly4 endpoints including:
- Assembly parsing and validation
- Constraint solving
- Collision detection
- DOF analysis
- CAM generation
- Export capabilities

Features:
- Async operation with Celery integration
- Idempotency support
- Rate limiting
- Turkish localization
- Comprehensive error handling
- OpenAPI documentation
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Header,
    Query,
    status,
    BackgroundTasks,
)
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.security import get_current_user
from ..core.environment import environment as settings
from ..core.logging import get_logger
from ..core import metrics
from ..models.job import Job
from ..models.user import User
from ..schemas.assembly4 import (
    Assembly4Request,
    Assembly4Response,
    Assembly4Input,
    AssemblyResult,
    CAMJobParameters,
    CollisionReport,
    DOFAnalysis,
    ExportOptions,
)
from ..services.assembly4_service import assembly4_service, Assembly4Exception, DOFAnalyzer
from ..services.job_control import is_queue_paused
from ..services.s3_service import s3_service
from ..tasks.assembly4_tasks import process_assembly4_task

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/assembly4",
    tags=["Assembly4 - Montaj ve CAM İşlemleri"],
    responses={
        403: {"description": "Yetkisiz erişim"},
        422: {"description": "Geçersiz giriş parametreleri"},
        429: {"description": "Rate limit aşıldı"},
        503: {"description": "Servis geçici olarak kullanılamıyor"},
    }
)


@router.post("/validate", response_model=Dict[str, any])
async def validate_assembly(
    request: Assembly4Input,
    current_user: User = Depends(get_current_user)
) -> Dict[str, any]:
    """
    Validate Assembly4 JSON input without processing.
    
    Validates:
    - Part references and model files
    - LCS definitions and references
    - Constraint consistency
    - Hierarchy structure
    """
    try:
        # Input is already validated by Pydantic
        # Additional business logic validation can be added here
        
        validation_result = {
            "valid": True,
            "parts_count": len(request.parts),
            "constraints_count": len(request.constraints),
            "lcs_count": len(request.lcs_definitions),
            "warnings": [],
            "info": {
                "solver_type": request.solver_type,
                "tolerance": request.tolerance
            }
        }
        
        # Check for potential issues
        if not request.constraints:
            validation_result["warnings"].append(
                "Kısıt tanımlanmamış - parçalar sabit olmayabilir"
            )
        
        # Use DOFAnalyzer service for constraint analysis
        dof_analyzer = DOFAnalyzer()
        # DOFAnalyzer.analyze expects (parts, constraints) not the full request
        dof_result = dof_analyzer.analyze(request.parts, request.constraints)
        
        if dof_result.is_over_constrained:
            validation_result["warnings"].append(
                f"Potansiyel aşırı kısıtlama: {dof_result.constrained_dof} DOF kısıtı, {dof_result.total_dof} DOF mevcut"
            )
        
        metrics.assembly_validations.labels(
            status="success",
            user_id=str(current_user.id)
        ).inc()
        
        return validation_result
        
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        metrics.assembly_validations.labels(
            status="failed",
            user_id=str(current_user.id)
        ).inc()
        
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Doğrulama hatası: {str(e)}"
        )


@router.post("/analyze/dof", response_model=DOFAnalysis)
async def analyze_dof(
    request: Assembly4Input,
    current_user: User = Depends(get_current_user)
) -> DOFAnalysis:
    """
    Analyze degrees of freedom for assembly.
    
    Returns:
    - Total DOF
    - Constrained DOF
    - Remaining DOF
    - Constraint breakdown
    - Mobility analysis
    """
    try:
        analyzer = DOFAnalyzer()
        # Pass parts and constraints separately as DOFAnalyzer.analyze expects
        result = analyzer.analyze(request.parts, request.constraints)
        
        metrics.assembly_analyses.labels(
            analysis_type="dof",
            user_id=str(current_user.id)
        ).inc()
        
        return result
        
    except Exception as e:
        logger.error(f"DOF analysis failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"DOF analizi başarısız: {str(e)}"
        )


@router.post("/process", response_model=Assembly4Response)
async def process_assembly(
    request: Assembly4Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
) -> Assembly4Response:
    """
    Process Assembly4 input to create assembly.
    
    Steps:
    1. Parse and validate input
    2. Create job record
    3. Queue assembly processing task
    4. Return job ID for tracking
    
    Processing includes:
    - Part loading and placement
    - Constraint solving (OndselSolver/fallback)
    - Collision detection
    - DOF analysis
    - Assembly building with App::Link
    - Export (FCStd, STEP, BOM)
    - Optional CAM generation
    """
    try:
        # Check if assembly queue is paused
        if is_queue_paused("assembly"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Assembly kuyruğu geçici olarak duraklatıldı"
            )
        
        # Check idempotency
        if idempotency_key:
            existing_job = db.query(Job).filter_by(
                idempotency_key=idempotency_key,
                type="assembly4"
            ).first()
            
            if existing_job:
                logger.info(f"Idempotent hit for key: {idempotency_key}")
                metrics.idempotent_hits.labels(
                    operation="assembly4_process"
                ).inc()
                
                return Assembly4Response(
                    job_id=str(existing_job.id),
                    status=existing_job.status
                )
        
        # Create job record
        job = Job(
            type="assembly4",
            status="pending",
            user_id=current_user.id,
            idempotency_key=idempotency_key,
            metrics={
                "request": request.model_dump(),
                "created_at": datetime.utcnow().isoformat(),
                "assembly_name": request.input.name,
                "parts_count": len(request.input.parts),
                "constraints_count": len(request.input.constraints),
                "generate_cam": request.generate_cam
            }
        )
        
        db.add(job)
        db.commit()
        db.refresh(job)
        
        # Queue processing task
        try:
            result = process_assembly4_task.delay(
                job_id=str(job.id),
                assembly_input=request.input.model_dump(),
                generate_cam=request.generate_cam,
                cam_parameters=request.cam_parameters.model_dump() if request.cam_parameters else None,
                export_options=request.export_options.model_dump()
            )
            
            # Update job with task ID
            job.task_id = result.id
            db.commit()
            
        except Exception as e:
            # If queueing fails, delete job
            db.delete(job)
            db.commit()
            
            logger.error(f"Failed to queue assembly task: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="İşlem kuyruğa alınamadı. Lütfen tekrar deneyin."
            )
        
        metrics.assembly_jobs_created.labels(
            solver_type=request.input.solver_type,
            with_cam="yes" if request.generate_cam else "no"
        ).inc()
        
        return Assembly4Response(
            job_id=str(job.id),
            status="queued"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Assembly processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"İşlem başlatılamadı: {str(e)}"
        )


@router.get("/jobs/{job_id}", response_model=Assembly4Response)
async def get_assembly_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Assembly4Response:
    """
    Get assembly job status and results.
    
    Returns:
    - Job status
    - Assembly results if completed
    - CAM results if generated
    - Signed URLs for downloads
    """
    try:
        # Get job from database
        job = db.query(Job).filter_by(
            id=job_id,
            type="assembly4"
        ).first()
        
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="İş bulunamadı"
            )
        
        # Check authorization
        if job.user_id != current_user.id and not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işe erişim yetkiniz yok"
            )
        
        response = Assembly4Response(
            job_id=str(job.id),
            status=job.status
        )
        
        # If job is completed, include results
        if job.status == "succeeded" and job.result:
            response.assembly_result = AssemblyResult(**job.result.get("assembly_result", {}))
            
            if job.result.get("cam_result"):
                response.cam_result = job.result["cam_result"]
            
            # Generate signed URLs for artifacts
            signed_urls = {}
            
            if job.artefacts:
                for artifact in job.artefacts:
                    if artifact.get("s3_key"):
                        url = s3_service.generate_presigned_url(
                            artifact["s3_key"],
                            expiration=3600  # 1 hour
                        )
                        signed_urls[artifact.get("type", "file")] = url
            
            response.signed_urls = signed_urls
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get assembly job: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"İş bilgisi alınamadı: {str(e)}"
        )


@router.post("/jobs/{job_id}/retry")
async def retry_assembly_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Retry a failed assembly job.
    """
    try:
        # Get original job
        job = db.query(Job).filter_by(
            id=job_id,
            type="assembly4"
        ).first()
        
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="İş bulunamadı"
            )
        
        # Check authorization
        if job.user_id != current_user.id and not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işe erişim yetkiniz yok"
            )
        
        # Check if job can be retried
        if job.status not in ["failed", "cancelled"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sadece başarısız veya iptal edilmiş işler tekrar denenebilir"
            )
        
        # Create new job with same parameters
        new_job = Job(
            type="assembly4",
            status="pending",
            user_id=current_user.id,
            metrics={
                **job.metrics,
                "retry_of": str(job.id),
                "created_at": datetime.utcnow().isoformat()
            }
        )
        
        db.add(new_job)
        db.commit()
        db.refresh(new_job)
        
        # Queue new task
        request_data = job.metrics.get("request", {})
        result = process_assembly4_task.delay(
            job_id=str(new_job.id),
            assembly_input=request_data.get("input", {}),
            generate_cam=request_data.get("generate_cam", False),
            cam_parameters=request_data.get("cam_parameters"),
            export_options=request_data.get("export_options", {})
        )
        
        new_job.task_id = result.id
        db.commit()
        
        metrics.assembly_jobs_retried.inc()
        
        return {
            "original_job_id": str(job.id),
            "new_job_id": str(new_job.id),
            "status": "queued"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to retry assembly job: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"İş tekrar başlatılamadı: {str(e)}"
        )


@router.delete("/jobs/{job_id}")
async def cancel_assembly_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> Dict[str, str]:
    """
    Cancel a pending or running assembly job.
    """
    try:
        # Get job
        job = db.query(Job).filter_by(
            id=job_id,
            type="assembly4"
        ).first()
        
        if not job:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="İş bulunamadı"
            )
        
        # Check authorization
        if job.user_id != current_user.id and not current_user.is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işe erişim yetkiniz yok"
            )
        
        # Check if job can be cancelled
        if job.status in ["succeeded", "failed", "cancelled"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"İş zaten {job.status} durumunda"
            )
        
        # Cancel Celery task if running
        if job.task_id:
            from ..core.celery_app import celery_app
            celery_app.control.revoke(job.task_id, terminate=True)
        
        # Update job status
        job.status = "cancelled"
        job.finished_at = datetime.utcnow()
        job.error_message = "Kullanıcı tarafından iptal edildi"
        
        db.commit()
        
        metrics.assembly_jobs_cancelled.inc()
        
        return {
            "job_id": str(job.id),
            "status": "cancelled",
            "message": "İş başarıyla iptal edildi"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel assembly job: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"İş iptal edilemedi: {str(e)}"
        )


@router.get("/jobs", response_model=List[Assembly4Response])
async def list_assembly_jobs(
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(10, ge=1, le=100, description="Number of items to return"),
    status: Optional[str] = Query(None, description="Filter by status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
) -> List[Assembly4Response]:
    """
    List assembly jobs for current user.
    """
    try:
        query = db.query(Job).filter_by(
            user_id=current_user.id,
            type="assembly4"
        )
        
        if status:
            query = query.filter_by(status=status)
        
        query = query.order_by(Job.created_at.desc())
        jobs = query.offset(skip).limit(limit).all()
        
        results = []
        for job in jobs:
            response = Assembly4Response(
                job_id=str(job.id),
                status=job.status
            )
            
            # Include basic metadata
            if job.metrics:
                assembly_input = job.metrics.get("request", {}).get("input", {})
                if assembly_input:
                    # Map job status to AssemblyResult status (which is a Literal)
                    result_status = "failed"  # default
                    if job.status in ("succeeded", "completed"):
                        result_status = "success"
                    elif job.status in ("pending", "queued", "processing"):
                        result_status = "partial"
                    
                    response.assembly_result = AssemblyResult(
                        job_id=str(job.id),
                        status=result_status,
                        errors=[job.error_message] if job.error_message else [],
                        warnings=[],
                        computation_time_ms=0
                    )
            
            results.append(response)
        
        return results
        
    except Exception as e:
        logger.error(f"Failed to list assembly jobs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"İş listesi alınamadı: {str(e)}"
        )


@router.get("/templates")
async def get_assembly_templates(
    current_user: User = Depends(get_current_user)
) -> List[Dict[str, any]]:
    """
    Get example Assembly4 JSON templates.
    """
    templates = [
        {
            "name": "Simple Two-Part Assembly",
            "description": "Basic assembly with two parts and attachment constraint",
            "template": {
                "name": "Simple Assembly",
                "parts": [
                    {
                        "id": "base",
                        "model_ref": "/models/base.FCStd",
                        "lcs_list": ["LCS_Top"]
                    },
                    {
                        "id": "top",
                        "model_ref": "/models/top.FCStd",
                        "lcs_list": ["LCS_Bottom"]
                    }
                ],
                "constraints": [
                    {
                        "type": "Attachment",
                        "reference1": {"part_id": "base", "lcs_name": "LCS_Top"},
                        "reference2": {"part_id": "top", "lcs_name": "LCS_Bottom"}
                    }
                ],
                "solver_type": "ondsel"
            }
        },
        {
            "name": "Gear Assembly",
            "description": "Gear mechanism with axis constraints",
            "template": {
                "name": "Gear Assembly",
                "parts": [
                    {
                        "id": "gear1",
                        "model_ref": "/models/gear.FCStd",
                        "lcs_list": ["LCS_Center", "LCS_Teeth"]
                    },
                    {
                        "id": "gear2",
                        "model_ref": "/models/gear.FCStd",
                        "lcs_list": ["LCS_Center", "LCS_Teeth"]
                    },
                    {
                        "id": "shaft",
                        "model_ref": "/models/shaft.FCStd",
                        "lcs_list": ["LCS_Axis"]
                    }
                ],
                "constraints": [
                    {
                        "type": "AxisCoincident",
                        "reference1": {"part_id": "gear1", "lcs_name": "LCS_Center"},
                        "reference2": {"part_id": "shaft", "lcs_name": "LCS_Axis"}
                    },
                    {
                        "type": "Offset",
                        "reference1": {"part_id": "gear1", "lcs_name": "LCS_Teeth"},
                        "reference2": {"part_id": "gear2", "lcs_name": "LCS_Teeth"},
                        "value": 50.0
                    }
                ],
                "solver_type": "ondsel"
            }
        }
    ]
    
    return templates