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
    job_type: JobType,
    current_user: AuthenticatedUser
) -> Optional[Job]:
    """
    Handle idempotency key checking and validation.
    
    Args:
        db: Database session
        idempotency_key: Idempotency key from header
        request_body: Request body for comparison
        job_type: Type of job being created
        current_user: The authenticated user making the request
        
    Returns:
        Existing job if found, None otherwise
        
    Raises:
        HTTPException: If idempotency conflict detected
    """
    if not idempotency_key:
        return None
    
    # CRITICAL: Check for existing job with same idempotency key FOR THE SAME USER AND JOB TYPE
    # This prevents data leakage between users and ensures idempotency is scoped per job type
    existing_job = db.query(Job).filter(
        Job.idempotency_key == idempotency_key,
        Job.user_id == current_user.user_id,
        Job.type == job_type
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
                existing_job_id=existing_job.id,
                user_id=current_user.user_id
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


def handle_integrity_error_with_idempotency(
    e: IntegrityError,
    db: Session,
    idempotency_key: Optional[str],
    body: DesignCreateRequest,
    job_type: JobType,
    current_user: AuthenticatedUser,
    response: Response,
    estimated_duration: int
) -> Optional[DesignJobResponse]:
    """
    Handle IntegrityError with idempotency key conflict detection.
    
    Args:
        e: The IntegrityError exception
        db: Database session
        idempotency_key: Optional idempotency key
        body: Request body
        job_type: Job type enum
        current_user: Authenticated user
        response: Response object for headers
        estimated_duration: Estimated job duration
        
    Returns:
        DesignJobResponse if duplicate found, None otherwise
        
    Raises:
        HTTPException: For database errors
    """
    db.rollback()
    
    # Check if it's a unique constraint violation on the idempotency key
    if hasattr(e, 'orig') and hasattr(e.orig, 'pgcode') and e.orig.pgcode == '23505':
        # This is a unique constraint violation - likely idempotency race condition
        logger.warning(
            "Idempotency race condition detected, re-fetching job",
            idempotency_key=idempotency_key,
            user_id=current_user.user_id
        )
        # Re-fetch the job created by the other request
        existing_job = handle_idempotency(
            db, idempotency_key, body.model_dump(), job_type, current_user
        )
        if existing_job:
            return create_duplicate_response(existing_job, response, estimated_duration)
    
    logger.error("Database integrity error", error=str(e))
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Veritabanı hatası oluştu"
    )


def create_job_from_design(
    db: Session,
    current_user: AuthenticatedUser,
    license: License,
    body: DesignCreateRequest,
    idempotency_key: Optional[str],
    job_type: JobType,
    input_type: str,
    extra_metadata: Dict[str, Any] = None
) -> Job:
    """
    Create a job from design request with proper type handling.
    
    Args:
        db: Database session
        current_user: Authenticated user
        license: Valid license
        body: Design request body
        idempotency_key: Idempotency key
        job_type: Type of job
        input_type: Type of input (prompt, params, upload, assembly)
        extra_metadata: Additional metadata to include
        
    Returns:
        Created job instance
        
    Raises:
        IntegrityError: If database constraint violated
    """
    metadata = {
        "input_type": input_type,
        "request_id": f"req_{uuid4().hex[:10]}",
        "chain_cam": body.chain_cam,
        "chain_sim": body.chain_sim
    }
    
    if extra_metadata:
        metadata.update(extra_metadata)
    
    job = Job(
        idempotency_key=idempotency_key,
        type=job_type,
        status=JobStatus.PENDING,
        params=body.model_dump(),
        user_id=current_user.user_id,
        license_id=license.id,
        tenant_id=current_user.tenant_id,
        priority=body.priority,
        metadata=metadata
    )
    
    db.add(job)
    db.commit()
    
    return job


def create_duplicate_response(
    existing_job: Job,
    response: Response,
    estimated_duration: int
) -> DesignJobResponse:
    """
    Create response for duplicate idempotent request.
    
    Args:
        existing_job: Existing job from idempotency check
        response: FastAPI response object
        estimated_duration: Estimated duration for this job type
        
    Returns:
        Design job response for duplicate request
    """
    set_version_headers(response)
    
    # Correctly determine queue from existing job's type
    routing_config = get_routing_config_for_job_type(existing_job.type)
    
    # Safely get request_id from metadata
    request_id = None
    if existing_job.metadata and isinstance(existing_job.metadata, dict):
        request_id = existing_job.metadata.get("request_id")
    
    # Use fallback if request_id not found
    if not request_id:
        logger.warning(
            "Missing request_id in job metadata, using fallback",
            job_id=existing_job.id
        )
        request_id = f"req_{existing_job.id}"
    
    return DesignJobResponse(
        job_id=existing_job.id,
        request_id=request_id,
        status="duplicate",
        queue=routing_config["queue"],
        estimated_duration=estimated_duration,
        created_at=existing_job.created_at
    )


def publish_job_and_respond(
    job: Job,
    current_user: AuthenticatedUser,
    license: License,
    response: Response,
    estimated_duration: int = 120
) -> DesignJobResponse:
    """
    Publish job to queue and return response.
    
    Args:
        job: Created job
        current_user: Authenticated user
        license: License used
        response: FastAPI response object
        estimated_duration: Estimated job duration in seconds
        
    Returns:
        Design job response
    """
    # Get routing configuration
    routing_config = get_routing_config_for_job_type(job.type)
    
    # Publish to queue
    task_payload = {
        "job_id": str(job.id),
        "type": job.type.value,
        "params": job.params,
        "submitted_by": str(current_user.user_id),
        "license_id": str(license.id),
        "tenant_id": current_user.tenant_id if current_user.tenant_id else None,
    }
    
    publish_job_task(task_payload, routing_config)
    
    logger.info(
        "Design job published to queue",
        job_id=job.id,
        user_id=current_user.user_id,
        job_type=job.type.value,
        queue=routing_config["queue"]
    )
    
    set_version_headers(response)
    return DesignJobResponse(
        job_id=job.id,
        request_id=job.metadata["request_id"],
        status="accepted",
        queue=routing_config["queue"],
        estimated_duration=estimated_duration,
        created_at=job.created_at
    )


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
        db, idempotency_key, body.model_dump(), JobType.MODEL, current_user
    )
    
    if existing_job:
        logger.info(
            "Returning existing job for idempotent request",
            job_id=existing_job.id,
            user_id=current_user.user_id
        )
        return create_duplicate_response(existing_job, response, 120)
    
    # Create new job using shared helper
    try:
        job = create_job_from_design(
            db=db,
            current_user=current_user,
            license=license,
            body=body,
            idempotency_key=idempotency_key,
            job_type=JobType.MODEL,
            input_type="prompt"
        )
        
        return publish_job_and_respond(
            job=job,
            current_user=current_user,
            license=license,
            response=response,
            estimated_duration=120
        )
        
    except IntegrityError as e:
        result = handle_integrity_error_with_idempotency(
            e, db, idempotency_key, body, JobType.MODEL, 
            current_user, response, 120
        )
        if result:
            return result


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
        db, idempotency_key, body.model_dump(), JobType.MODEL, current_user
    )
    
    if existing_job:
        logger.info(
            "Returning existing job for idempotent request",
            job_id=existing_job.id,
            user_id=current_user.user_id
        )
        return create_duplicate_response(existing_job, response, 60)
    
    # Create new job using shared helper
    try:
        job = create_job_from_design(
            db=db,
            current_user=current_user,
            license=license,
            body=body,
            idempotency_key=idempotency_key,
            job_type=JobType.MODEL,
            input_type="params",
            extra_metadata={"template_id": body.design.template_id}
        )
        
        return publish_job_and_respond(
            job=job,
            current_user=current_user,
            license=license,
            response=response,
            estimated_duration=60
        )
        
    except IntegrityError as e:
        result = handle_integrity_error_with_idempotency(
            e, db, idempotency_key, body, JobType.MODEL, 
            current_user, response, 60
        )
        if result:
            return result


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
    
    # Verify file exists in S3 with proper error handling
    try:
        exists = s3_service.object_exists(body.design.s3_key)
    except Exception as e:
        logger.error("S3 service error during object_exists", error=str(e), s3_key=body.design.s3_key)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="S3 servisi ile iletişim kurulamadı. Lütfen daha sonra tekrar deneyin."
        )
    
    if not exists:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Dosya bulunamadı: {body.design.s3_key}"
        )
    
    # Handle idempotency - upload uses CAD_IMPORT job type
    existing_job = handle_idempotency(
        db, idempotency_key, body.model_dump(), JobType.CAD_IMPORT, current_user
    )
    
    if existing_job:
        logger.info(
            "Returning existing job for idempotent request",
            job_id=existing_job.id,
            user_id=current_user.user_id
        )
        return create_duplicate_response(existing_job, response, 90)
    
    # Create new job using shared helper
    try:
        job = create_job_from_design(
            db=db,
            current_user=current_user,
            license=license,
            body=body,
            idempotency_key=idempotency_key,
            job_type=JobType.CAD_IMPORT,
            input_type="upload",
            extra_metadata={
                "s3_key": body.design.s3_key,
                "file_format": body.design.file_format
            }
        )
        
        return publish_job_and_respond(
            job=job,
            current_user=current_user,
            license=license,
            response=response,
            estimated_duration=90
        )
        
    except IntegrityError as e:
        result = handle_integrity_error_with_idempotency(
            e, db, idempotency_key, body, JobType.CAD_IMPORT, 
            current_user, response, 90
        )
        if result:
            return result


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
            detail="Bu endpoint sadece 'Assembly4Input' tipi girdi kabul eder"
        )
    
    # Apply rate limits
    apply_rate_limits(request, current_user, "global")
    
    # Check license validity and features
    license = check_license_validity(
        current_user, db, ["assembly_design", "model_creation"]
    )
    
    # Handle idempotency - assembly4 uses ASSEMBLY job type
    existing_job = handle_idempotency(
        db, idempotency_key, body.model_dump(), JobType.ASSEMBLY, current_user
    )
    
    if existing_job:
        logger.info(
            "Returning existing job for idempotent request",
            job_id=existing_job.id,
            user_id=current_user.user_id
        )
        return create_duplicate_response(existing_job, response, 180)
    
    # Create new job using shared helper
    try:
        job = create_job_from_design(
            db=db,
            current_user=current_user,
            license=license,
            body=body,
            idempotency_key=idempotency_key,
            job_type=JobType.ASSEMBLY,
            input_type="assembly4",
            extra_metadata={
                "part_count": len(body.design.parts),
                "constraint_count": len(body.design.constraints)
            }
        )
        
        return publish_job_and_respond(
            job=job,
            current_user=current_user,
            license=license,
            response=response,
            estimated_duration=180
        )
        
    except IntegrityError as e:
        result = handle_integrity_error_with_idempotency(
            e, db, idempotency_key, body, JobType.ASSEMBLY, 
            current_user, response, 180
        )
        if result:
            return result