"""
Design API v1 Router - Task 7.1
Enterprise-grade model generation endpoints with comprehensive guards.

Implements:
- POST /api/v1/designs/prompt - AI-powered generation
- POST /api/v1/designs/params - Parametric generation
- POST /api/v1/designs/upload - File upload processing
- POST /api/v1/assemblies/a4 - Assembly4 generation
- GET /jobs/:id - Job status polling
- GET /jobs/:id/artefacts - Artefact listing

Features:
- JWT authentication with license and RBAC checks
- Rate limiting with Redis sliding window
- Idempotency key handling
- Turkish error messages
- OpenAPI documentation
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import structlog

from ..core.config import settings
from ..core.rate_limiter import RateLimiter
from ..db import get_db
from ..dependencies.auth_dependencies import require_scopes
from ..middleware.jwt_middleware import AuthenticatedUser
from ..models import Job, User, License, Artefact
from ..models.enums import JobStatus, JobType
from ..schemas.design_v2 import (
    DesignCreateRequest,
    DesignJobResponse,
    JobStatusResponse,
    JobArtefactsResponse,
    ArtefactResponse,
    RateLimitError,
    ValidationError,
    AuthorizationError,
    IdempotencyError,
    DesignPromptInput,
    DesignParametricInput,
    DesignUploadInput,
    Assembly4Input,
)
from ..services.job_queue_service import JobQueueService
from ..services.license_service import LicenseService
from ..storage import s3_service
from ..core.job_routing import get_routing_config_for_job_type
from ..core.job_validator import validate_job_payload, publish_job_task

logger = structlog.get_logger(__name__)

# Rate limiters for different endpoints
global_rate_limiter = RateLimiter(
    max_requests=60,
    window_seconds=60,
    key_prefix="design_global"
)

prompt_rate_limiter = RateLimiter(
    max_requests=30,
    window_seconds=60,
    key_prefix="design_prompt"
)

# Create router with version prefix
router = APIRouter(
    prefix="/api/v1",
    tags=["Model Generation v1"],
    responses={
        401: {"description": "Kimlik doğrulama gerekli"},
        403: {"description": "Yetersiz yetki"},
        429: {"description": "Rate limit aşıldı"},
    }
)


def check_license_validity(
    user: AuthenticatedUser,
    db: Session,
    required_features: list[str]
) -> License:
    """
    Check if user has valid license with required features.
    
    Args:
        user: Authenticated user
        db: Database session
        required_features: List of required license features
        
    Returns:
        Valid license object
        
    Raises:
        HTTPException: If license is invalid or missing features
    """
    license_service = LicenseService(db)
    
    # Get user's active license
    license = license_service.get_user_active_license(user.user_id)
    
    if not license:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Aktif lisans bulunamadı"
        )
    
    # Check license validity
    if not license_service.is_license_valid(license):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Lisans süresi dolmuş veya geçersiz"
        )
    
    # Check required features
    for feature in required_features:
        if not license_service.has_feature(license, feature):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Lisansınız {feature} özelliğini içermiyor"
            )
    
    return license


def apply_rate_limits(
    request: Request,
    user: AuthenticatedUser,
    endpoint_type: str = "global"
) -> None:
    """
    Apply rate limiting with proper headers.
    
    Args:
        request: FastAPI request
        user: Authenticated user
        endpoint_type: Type of endpoint for specific limits
        
    Raises:
        HTTPException: If rate limit exceeded
    """
    user_key = str(user.user_id)
    
    # Check global rate limit
    if not global_rate_limiter.check_rate_limit(user_key):
        remaining, reset_in = global_rate_limiter.get_remaining(user_key)
        reset_at = datetime.now(timezone.utc) + timedelta(seconds=reset_in)
        
        logger.warning(
            "Global rate limit exceeded",
            user_id=user.user_id,
            endpoint=request.url.path
        )
        
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=RateLimitError(
                message=f"Genel rate limit aşıldı. {reset_in} saniye sonra tekrar deneyin.",
                retry_after=reset_in,
                limit=60,
                remaining=remaining,
                reset_at=reset_at
            ).model_dump()
        )
    
    # Check endpoint-specific rate limit for prompt endpoint
    if endpoint_type == "prompt":
        if not prompt_rate_limiter.check_rate_limit(user_key):
            remaining, reset_in = prompt_rate_limiter.get_remaining(user_key)
            reset_at = datetime.now(timezone.utc) + timedelta(seconds=reset_in)
            
            logger.warning(
                "Prompt rate limit exceeded",
                user_id=user.user_id,
                endpoint=request.url.path
            )
            
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=RateLimitError(
                    message=f"AI prompt rate limit aşıldı. {reset_in} saniye sonra tekrar deneyin.",
                    retry_after=reset_in,
                    limit=30,
                    remaining=remaining,
                    reset_at=reset_at
                ).model_dump()
            )


def handle_idempotency(
    db: Session,
    idempotency_key: Optional[str],
    request_body: Dict[str, Any],
    job_type: JobType
) -> Optional[Job]:
    """
    Handle idempotency key checking and validation.
    
    Args:
        db: Database session
        idempotency_key: Idempotency key from header
        request_body: Request body for comparison
        job_type: Type of job being created
        
    Returns:
        Existing job if found, None otherwise
        
    Raises:
        HTTPException: If idempotency conflict detected
    """
    if not idempotency_key:
        return None
    
    # Check for existing job with same idempotency key
    existing_job = db.query(Job).filter(
        Job.idempotency_key == idempotency_key
    ).first()
    
    if existing_job:
        # Compare request body hash
        request_hash = hashlib.sha256(
            json.dumps(request_body, sort_keys=True).encode()
        ).hexdigest()
        
        existing_hash = hashlib.sha256(
            json.dumps(existing_job.params, sort_keys=True).encode()
        ).hexdigest()
        
        if request_hash != existing_hash:
            logger.warning(
                "Idempotency conflict detected",
                idempotency_key=idempotency_key,
                existing_job_id=existing_job.id
            )
            
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=IdempotencyError(
                    message="Aynı idempotency key ile farklı istek gönderildi",
                    existing_job_id=existing_job.id,
                    request_mismatch=True
                ).model_dump()
            )
        
        return existing_job
    
    return None


def set_version_headers(response: Response) -> None:
    """Set API version headers."""
    response.headers["API-Version"] = "1"
    response.headers["X-API-Version"] = "1"


@router.post(
    "/designs/prompt",
    response_model=DesignJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="AI-Powered Design Generation",
    description="Generate 3D models from natural language prompts using AI"
)
async def create_design_from_prompt(
    request: Request,
    response: Response,
    body: DesignCreateRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_scopes("models:write")),
    db: Session = Depends(get_db)
) -> DesignJobResponse:
    """
    Create design job from AI prompt.
    
    Requires:
    - JWT authentication with models:write scope
    - Valid license with AI generation feature
    - Rate limits: 60/min global, 30/min for prompts
    """
    # Validate input type
    if not isinstance(body.design, DesignPromptInput):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Bu endpoint sadece 'prompt' tipi girdi kabul eder"
        )
    
    # Apply rate limits
    apply_rate_limits(request, current_user, "prompt")
    
    # Check license validity and features
    license = check_license_validity(
        current_user, db, ["ai_generation", "model_creation"]
    )
    
    # Handle idempotency
    existing_job = handle_idempotency(
        db, idempotency_key, body.model_dump(), JobType.MODEL_GENERATION
    )
    
    if existing_job:
        logger.info(
            "Returning existing job for idempotent request",
            job_id=existing_job.id,
            user_id=current_user.user_id
        )
        
        set_version_headers(response)
        return DesignJobResponse(
            job_id=existing_job.id,
            request_id=f"req_{existing_job.id}",
            status="duplicate",
            queue="model",
            estimated_duration=120,
            created_at=existing_job.created_at
        )
    
    # Create new job
    try:
        job = Job(
            idempotency_key=idempotency_key,
            type=JobType.MODEL_GENERATION,
            status=JobStatus.PENDING,
            params=body.model_dump(),
            user_id=UUID(current_user.user_id),
            license_id=license.id,
            tenant_id=UUID(current_user.tenant_id) if current_user.tenant_id else None,
            priority=body.priority,
            metadata={
                "input_type": "prompt",
                "request_id": f"req_{uuid4().hex[:10]}",
                "chain_cam": body.chain_cam,
                "chain_sim": body.chain_sim
            }
        )
        
        db.add(job)
        db.commit()
        
        # Get routing configuration
        routing_config = get_routing_config_for_job_type(JobType.MODEL_GENERATION)
        
        # Publish to queue
        task_payload = {
            "job_id": str(job.id),
            "type": "model_generation",
            "params": body.model_dump(),
            "submitted_by": str(current_user.user_id),
            "license_id": str(license.id),
            "tenant_id": str(current_user.tenant_id) if current_user.tenant_id else None,
        }
        
        publish_job_task(task_payload, routing_config)
        
        logger.info(
            "Design job created from prompt",
            job_id=job.id,
            user_id=current_user.user_id,
            queue=routing_config["queue"]
        )
        
        set_version_headers(response)
        return DesignJobResponse(
            job_id=job.id,
            request_id=job.metadata["request_id"],
            status="accepted",
            queue=routing_config["queue"],
            estimated_duration=120,
            created_at=job.created_at
        )
        
    except IntegrityError as e:
        db.rollback()
        logger.error("Database integrity error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Veritabanı hatası oluştu"
        )


@router.post(
    "/designs/params",
    response_model=DesignJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Parametric Design Generation",
    description="Generate 3D models from parametric specifications"
)
async def create_design_from_params(
    request: Request,
    response: Response,
    body: DesignCreateRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_scopes("models:write")),
    db: Session = Depends(get_db)
) -> DesignJobResponse:
    """
    Create design job from parametric input.
    
    Requires:
    - JWT authentication with models:write scope
    - Valid license with parametric design feature
    - Rate limit: 60/min global
    """
    # Validate input type
    if not isinstance(body.design, DesignParametricInput):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Bu endpoint sadece 'params' tipi girdi kabul eder"
        )
    
    # Apply rate limits
    apply_rate_limits(request, current_user, "global")
    
    # Check license validity and features
    license = check_license_validity(
        current_user, db, ["parametric_design", "model_creation"]
    )
    
    # Handle idempotency
    existing_job = handle_idempotency(
        db, idempotency_key, body.model_dump(), JobType.MODEL_GENERATION
    )
    
    if existing_job:
        logger.info(
            "Returning existing job for idempotent request",
            job_id=existing_job.id,
            user_id=current_user.user_id
        )
        
        set_version_headers(response)
        return DesignJobResponse(
            job_id=existing_job.id,
            request_id=f"req_{existing_job.id}",
            status="duplicate",
            queue="model",
            estimated_duration=60,
            created_at=existing_job.created_at
        )
    
    # Create new job
    try:
        job = Job(
            idempotency_key=idempotency_key,
            type=JobType.MODEL_GENERATION,
            status=JobStatus.PENDING,
            params=body.model_dump(),
            user_id=UUID(current_user.user_id),
            license_id=license.id,
            tenant_id=UUID(current_user.tenant_id) if current_user.tenant_id else None,
            priority=body.priority,
            metadata={
                "input_type": "params",
                "request_id": f"req_{uuid4().hex[:10]}",
                "template_id": body.design.template_id,
                "chain_cam": body.chain_cam,
                "chain_sim": body.chain_sim
            }
        )
        
        db.add(job)
        db.commit()
        
        # Get routing configuration
        routing_config = get_routing_config_for_job_type(JobType.MODEL_GENERATION)
        
        # Publish to queue
        task_payload = {
            "job_id": str(job.id),
            "type": "model_generation",
            "params": body.model_dump(),
            "submitted_by": str(current_user.user_id),
            "license_id": str(license.id),
            "tenant_id": str(current_user.tenant_id) if current_user.tenant_id else None,
        }
        
        publish_job_task(task_payload, routing_config)
        
        logger.info(
            "Design job created from parameters",
            job_id=job.id,
            user_id=current_user.user_id,
            template_id=body.design.template_id,
            queue=routing_config["queue"]
        )
        
        set_version_headers(response)
        return DesignJobResponse(
            job_id=job.id,
            request_id=job.metadata["request_id"],
            status="accepted",
            queue=routing_config["queue"],
            estimated_duration=60,
            created_at=job.created_at
        )
        
    except IntegrityError as e:
        db.rollback()
        logger.error("Database integrity error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Veritabanı hatası oluştu"
        )


@router.post(
    "/designs/upload",
    response_model=DesignJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Design File Upload Processing",
    description="Process uploaded design files for conversion or analysis"
)
async def create_design_from_upload(
    request: Request,
    response: Response,
    body: DesignCreateRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_scopes("models:write")),
    db: Session = Depends(get_db)
) -> DesignJobResponse:
    """
    Process uploaded design file.
    
    Requires:
    - JWT authentication with models:write scope
    - Valid license with file import feature
    - Rate limit: 60/min global
    """
    # Validate input type
    if not isinstance(body.design, DesignUploadInput):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Bu endpoint sadece 'upload' tipi girdi kabul eder"
        )
    
    # Apply rate limits
    apply_rate_limits(request, current_user, "global")
    
    # Check license validity and features
    license = check_license_validity(
        current_user, db, ["file_import", "model_creation"]
    )
    
    # Verify file exists in S3
    if not s3_service.object_exists(body.design.s3_key):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Dosya bulunamadı: {body.design.s3_key}"
        )
    
    # Handle idempotency
    existing_job = handle_idempotency(
        db, idempotency_key, body.model_dump(), JobType.MODEL_GENERATION
    )
    
    if existing_job:
        logger.info(
            "Returning existing job for idempotent request",
            job_id=existing_job.id,
            user_id=current_user.user_id
        )
        
        set_version_headers(response)
        return DesignJobResponse(
            job_id=existing_job.id,
            request_id=f"req_{existing_job.id}",
            status="duplicate",
            queue="model",
            estimated_duration=30,
            created_at=existing_job.created_at
        )
    
    # Create new job
    try:
        job = Job(
            idempotency_key=idempotency_key,
            type=JobType.MODEL_GENERATION,
            status=JobStatus.PENDING,
            params=body.model_dump(),
            user_id=UUID(current_user.user_id),
            license_id=license.id,
            tenant_id=UUID(current_user.tenant_id) if current_user.tenant_id else None,
            priority=body.priority,
            metadata={
                "input_type": "upload",
                "request_id": f"req_{uuid4().hex[:10]}",
                "s3_key": body.design.s3_key,
                "file_format": body.design.file_format,
                "chain_cam": body.chain_cam,
                "chain_sim": body.chain_sim
            }
        )
        
        db.add(job)
        db.commit()
        
        # Get routing configuration
        routing_config = get_routing_config_for_job_type(JobType.MODEL_GENERATION)
        
        # Publish to queue
        task_payload = {
            "job_id": str(job.id),
            "type": "model_generation",
            "params": body.model_dump(),
            "submitted_by": str(current_user.user_id),
            "license_id": str(license.id),
            "tenant_id": str(current_user.tenant_id) if current_user.tenant_id else None,
        }
        
        publish_job_task(task_payload, routing_config)
        
        logger.info(
            "Design job created from upload",
            job_id=job.id,
            user_id=current_user.user_id,
            s3_key=body.design.s3_key,
            queue=routing_config["queue"]
        )
        
        set_version_headers(response)
        return DesignJobResponse(
            job_id=job.id,
            request_id=job.metadata["request_id"],
            status="accepted",
            queue=routing_config["queue"],
            estimated_duration=30,
            created_at=job.created_at
        )
        
    except IntegrityError as e:
        db.rollback()
        logger.error("Database integrity error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Veritabanı hatası oluştu"
        )


@router.post(
    "/assemblies/a4",
    response_model=DesignJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Assembly4 Assembly Generation",
    description="Generate complex assemblies using Assembly4 workbench"
)
async def create_assembly4(
    request: Request,
    response: Response,
    body: DesignCreateRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: AuthenticatedUser = Depends(require_scopes("models:write")),
    db: Session = Depends(get_db)
) -> DesignJobResponse:
    """
    Create Assembly4 assembly job.
    
    Requires:
    - JWT authentication with models:write scope
    - Valid license with assembly feature
    - Rate limit: 60/min global
    """
    # Validate input type
    if not isinstance(body.design, Assembly4Input):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Bu endpoint sadece 'a4' tipi girdi kabul eder"
        )
    
    # Apply rate limits
    apply_rate_limits(request, current_user, "global")
    
    # Check license validity and features
    license = check_license_validity(
        current_user, db, ["assembly_design", "model_creation"]
    )
    
    # Handle idempotency
    existing_job = handle_idempotency(
        db, idempotency_key, body.model_dump(), JobType.MODEL_GENERATION
    )
    
    if existing_job:
        logger.info(
            "Returning existing job for idempotent request",
            job_id=existing_job.id,
            user_id=current_user.user_id
        )
        
        set_version_headers(response)
        return DesignJobResponse(
            job_id=existing_job.id,
            request_id=f"req_{existing_job.id}",
            status="duplicate",
            queue="model",
            estimated_duration=180,
            created_at=existing_job.created_at
        )
    
    # Create new job
    try:
        job = Job(
            idempotency_key=idempotency_key,
            type=JobType.MODEL_GENERATION,
            status=JobStatus.PENDING,
            params=body.model_dump(),
            user_id=UUID(current_user.user_id),
            license_id=license.id,
            tenant_id=UUID(current_user.tenant_id) if current_user.tenant_id else None,
            priority=body.priority,
            metadata={
                "input_type": "assembly4",
                "request_id": f"req_{uuid4().hex[:10]}",
                "part_count": len(body.design.parts),
                "constraint_count": len(body.design.constraints),
                "chain_cam": body.chain_cam,
                "chain_sim": body.chain_sim
            }
        )
        
        db.add(job)
        db.commit()
        
        # Get routing configuration
        routing_config = get_routing_config_for_job_type(JobType.MODEL_GENERATION)
        
        # Publish to queue
        task_payload = {
            "job_id": str(job.id),
            "type": "model_generation",
            "params": body.model_dump(),
            "submitted_by": str(current_user.user_id),
            "license_id": str(license.id),
            "tenant_id": str(current_user.tenant_id) if current_user.tenant_id else None,
        }
        
        publish_job_task(task_payload, routing_config)
        
        logger.info(
            "Assembly4 job created",
            job_id=job.id,
            user_id=current_user.user_id,
            part_count=len(body.design.parts),
            queue=routing_config["queue"]
        )
        
        set_version_headers(response)
        return DesignJobResponse(
            job_id=job.id,
            request_id=job.metadata["request_id"],
            status="accepted",
            queue=routing_config["queue"],
            estimated_duration=180,
            created_at=job.created_at
        )
        
    except IntegrityError as e:
        db.rollback()
        logger.error("Database integrity error", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Veritabanı hatası oluştu"
        )