from __future__ import annotations

import json
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query, status, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
import structlog

from ..models import Job, User
from ..models.enums import JobStatus, JobType, UserRole
from ..storage import presigned_url
from ..services.job_control import queue_pause, queue_resume
from ..services.job_queue_service import JobQueueService
from ..services.job_cancellation_service import job_cancellation_service
from ..security.oidc import require_role
from ..db import db_session, get_db
from ..schemas.job_create import (
    JobCreateRequest,
    JobCreateResponse,
    JobErrorResponse,
    RateLimitErrorResponse,
)
from ..schemas.job_status import (
    JobStatusResponse,
    JobProgressResponse,
    JobErrorResponse as JobLastErrorResponse,
    ArtefactResponse,
)
from ..core.job_validator import (
    JobValidationError,
    validate_job_payload,
    publish_job_task,
    get_job_error_response,
)
from ..core.job_routing import get_routing_config_for_job_type
from ..core.rate_limiter import RateLimiter
from ..core.auth import get_current_user
from ..core.config import settings
from kombu.exceptions import OperationalError
from ..services.job_audit_service import job_audit_service

logger = structlog.get_logger(__name__)

# Error code constants for enterprise quality (Copilot feedback)
ERROR_CODE_VALIDATION = "ERR-JOB-422"
ERROR_CODE_CONFLICT = "ERR-JOB-409"
ERROR_CODE_INTERNAL = "ERR-JOB-500"
ERROR_CODE_BAD_REQUEST = "ERR-JOB-400"

# Rate limiters for Task 6.4
per_user_rate_limiter = RateLimiter(
    max_requests=60,
    window_seconds=60,
    key_prefix="job_create_user"
)

global_rate_limiter = RateLimiter(
    max_requests=500,
    window_seconds=60,
    key_prefix="job_create_global"
)

router = APIRouter(prefix="/api/v1/jobs", tags=["İşler"])


@router.post(
    "",
    response_model=JobCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        200: {"model": JobCreateResponse, "description": "Existing job returned (idempotent)"},
        201: {"model": JobCreateResponse, "description": "New job created"},
        409: {"model": JobErrorResponse, "description": "Database conflict"},
        422: {"model": JobErrorResponse, "description": "Invalid type or params"},
        429: {"model": RateLimitErrorResponse, "description": "Rate limit exceeded"},
        500: {"model": JobErrorResponse, "description": "Internal server error"},
    }
)
async def create_job(
    request: Request,
    response: Response,
    job_request: JobCreateRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
) -> JobCreateResponse:
    """
    İş oluştur - idempotency ile.
    Create a new job with idempotency support.
    
    Task 6.4 Implementation:
    - Idempotent creation with unique idempotency_key
    - Transactional database operations
    - Rate limiting (per-user: 60/min, global: 500/min)
    - Automatic queue routing based on job type
    - Returns existing job on idempotent hit (200)
    - Returns new job with Location header (201)
    """
    
    # Get user identifier for rate limiting
    user_key = str(current_user.id) if current_user else request.client.host
    
    # Check per-user rate limit
    if not per_user_rate_limiter.check_rate_limit(user_key):
        remaining, reset_in = per_user_rate_limiter.get_remaining(user_key)
        logger.warning(
            "Per-user rate limit exceeded",
            user_key=user_key,
            remaining=remaining,
            reset_in=reset_in,
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=RateLimitErrorResponse(
                message=f"Rate limit exceeded for user. Please try again in {reset_in} seconds.",
                remaining=remaining,
                reset_in=reset_in,
                limit=60,
            ).dict(),
        )
    
    # Check global rate limit
    if not global_rate_limiter.check_rate_limit("global"):
        remaining, reset_in = global_rate_limiter.get_remaining("global")
        logger.warning(
            "Global rate limit exceeded",
            remaining=remaining,
            reset_in=reset_in,
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content=RateLimitErrorResponse(
                message=f"Global rate limit exceeded. Please try again in {reset_in} seconds.",
                remaining=remaining,
                reset_in=reset_in,
                limit=500,
            ).dict(),
        )
    
    # GEMINI HIGH FIX: Check JSON payload size (256KB limit)
    # Use JSON serialization to get accurate byte size, not sys.getsizeof
    payload_json = json.dumps(job_request.params)
    payload_size = len(payload_json.encode('utf-8'))
    MAX_PAYLOAD_SIZE = 256 * 1024  # 256KB
    
    if payload_size > MAX_PAYLOAD_SIZE:
        logger.warning(
            "Payload size exceeds 256KB limit",
            payload_size=payload_size,
            max_size=MAX_PAYLOAD_SIZE,
            idempotency_key=job_request.idempotency_key,
        )
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content=JobErrorResponse(
                error="ERR-JOB-413",
                message=f"Payload size ({payload_size} bytes) exceeds maximum allowed size ({MAX_PAYLOAD_SIZE} bytes). Large artifacts should be referenced via object storage keys.",
                details={
                    "payload_size": payload_size,
                    "max_size": MAX_PAYLOAD_SIZE,
                    "recommendation": "Store large data in S3/MinIO and reference by key"
                },
                retryable=False,
            ).dict(),
        )
    
    # GEMINI HIGH PRIORITY FIX: Check idempotency BEFORE validation for efficiency
    # This avoids unnecessary validation work for duplicate requests
    existing_job = db.query(Job).filter(
        Job.idempotency_key == job_request.idempotency_key
    ).first()
    
    if existing_job:
        # Idempotent hit - return existing job immediately without validation
        logger.info(
            "Idempotent job request - returning existing job (early check)",
            job_id=existing_job.id,
            idempotency_key=job_request.idempotency_key,
        )
        
        # Use centralized routing logic to get the queue for the existing job.
        try:
            routing_config = get_routing_config_for_job_type(existing_job.type)
        except ValueError:
            # Fallback for safety, though this should not happen for a job type in the DB.
            logger.warning(
                "Could not determine routing for existing idempotent job, using fallback.",
                job_id=existing_job.id,
                job_type=existing_job.type.value,
            )
            routing_config = {"queue": "default"}
        
        response.status_code = status.HTTP_200_OK
        return JobCreateResponse(
            id=existing_job.id,
            type=existing_job.type,
            status=existing_job.status,
            idempotency_key=existing_job.idempotency_key,
            created_at=existing_job.created_at,
            task_id=existing_job.task_id,
            queue=routing_config["queue"],
            message="Job already exists (idempotent request)",
            is_duplicate=True,
        )
    
    # Only validate if job doesn't exist (new job creation)
    try:
        # Prepare job data for validation
        job_data = {
            "type": job_request.type.value if isinstance(job_request.type, JobType) else job_request.type,
            "params": job_request.params,
            "job_id": str(uuid4()),
            "submitted_by": str(current_user.id) if current_user else "anonymous",
            "attempt": 0,
            "created_at": datetime.utcnow(),
        }
        
        # Validate job payload using Task 6.3 validator
        task_payload, routing_config = validate_job_payload(job_data)
        
    except JobValidationError as e:
        logger.warning(
            "Job validation failed",
            error_code=e.error_code,
            message=e.message,
            details=e.details,
        )
        
        # Return 422 for validation errors
        if e.error_code == ERROR_CODE_VALIDATION:
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                content=get_job_error_response(e),
            )
        # Return 400 for other job errors
        else:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content=get_job_error_response(e),
            )
    
    # Start database transaction for new job creation
    try:
        # Create new job
        new_job = Job(
            idempotency_key=job_request.idempotency_key,
            type=job_request.type,
            status=JobStatus.PENDING,
            params=job_request.params,
            user_id=getattr(current_user, "id", None),
            priority=job_request.priority or 0,
            progress=0,
            attempts=0,
            cancel_requested=False,
            retry_count=0,
            max_retries=routing_config.get("max_retries", 3),
            timeout_seconds=routing_config.get("timeout_seconds", 3600),
        )
        
        # Add and flush to get the ID
        db.add(new_job)
        db.flush()
        
        # Update task_payload with actual job_id
        task_payload.job_id = str(new_job.id)
        
        # Commit the transaction before publishing
        db.commit()
        
        # Audit log the job creation (Task 6.8)
        try:
            await job_audit_service.audit_job_created(
                db=db,
                job=new_job,
                actor_id=getattr(current_user, "id", None),
                metadata={
                    "queue": routing_config["queue"],
                    "routing_key": routing_config["routing_key"],
                    "priority": job_request.priority or 0,
                }
            )
            db.commit()
        except Exception as audit_error:
            # Log but don't fail the request if audit fails
            logger.error(
                "Failed to create audit log for job creation",
                job_id=new_job.id,
                error=str(audit_error),
            )
        
        logger.info(
            "Job created successfully",
            job_id=new_job.id,
            job_type=new_job.type.value,
            idempotency_key=new_job.idempotency_key,
        )
        
        # Publish task to queue (after commit)
        try:
            publish_result = publish_job_task(task_payload, routing_config)
            
            # Update job with task_id
            new_job.task_id = publish_result.job_id
            new_job.status = JobStatus.QUEUED
            db.commit()
            
            # Audit log the job queued event (Task 6.8)
            try:
                await job_audit_service.audit_job_queued(
                    db=db,
                    job_id=new_job.id,
                    queue_name=routing_config["queue"],
                    routing_key=routing_config["routing_key"],
                    actor_id=None,  # System action
                    metadata={
                        "task_id": publish_result.job_id,
                        "exchange": routing_config.get("exchange", "jobs"),
                    }
                )
                db.commit()
            except Exception as audit_error:
                logger.error(
                    "Failed to create audit log for job queued",
                    job_id=new_job.id,
                    error=str(audit_error),
                )
            
            logger.info(
                "Job task published successfully",
                job_id=new_job.id,
                task_id=publish_result.job_id,
                queue=routing_config["queue"],
            )
            
        except OperationalError as e:
            logger.error(
                "Failed to publish job task - broker connection issue",
                job_id=new_job.id,
                error=str(e),
                error_type=type(e).__name__,
            )
            # Job is created but not queued - leave as PENDING
            # Don't fail the request since job is already persisted
        
        # Set Location header for new resource
        response.headers["Location"] = f"/api/v1/jobs/{new_job.id}"
        
        return JobCreateResponse(
            id=new_job.id,
            type=new_job.type,
            status=new_job.status,
            idempotency_key=new_job.idempotency_key,
            created_at=new_job.created_at,
            task_id=new_job.task_id,
            queue=routing_config["queue"],
            message=f"Job created and queued to {routing_config['queue']}",
            is_duplicate=False,
        )
        
    except IntegrityError as e:
        db.rollback()
        
        # Handle unique constraint violation (race condition)
        if "idempotency_key" in str(e):
            # Try to fetch the job that was just created by another request
            existing_job = db.query(Job).filter(
                Job.idempotency_key == job_request.idempotency_key
            ).first()
            
            if existing_job:
                logger.info(
                    "Race condition resolved - returning existing job",
                    job_id=existing_job.id,
                    idempotency_key=job_request.idempotency_key,
                )
                
                # GEMINI HIGH PRIORITY FIX: Recalculate routing_config for the existing job
                # The original routing_config was for the new job that failed to insert
                try:
                    _, race_routing_config = validate_job_payload({
                        "type": existing_job.type.value,
                        "params": existing_job.params,
                        "job_id": str(existing_job.id),
                        "submitted_by": str(existing_job.user_id) if existing_job.user_id else "anonymous",
                        "attempt": 0,
                        "created_at": existing_job.created_at,
                    })
                except JobValidationError as e:
                    # This should be rare, but as a fallback, get routing directly.
                    logger.warning(
                        "Could not re-validate existing job during race condition, falling back to direct routing lookup.",
                        job_id=existing_job.id,
                        error=str(e),
                    )
                    try:
                        race_routing_config = get_routing_config_for_job_type(existing_job.type)
                    except ValueError:
                        # Final fallback if even direct routing lookup fails.
                        race_routing_config = {"queue": "default"}
                
                response.status_code = status.HTTP_200_OK
                return JobCreateResponse(
                    id=existing_job.id,
                    type=existing_job.type,
                    status=existing_job.status,
                    idempotency_key=existing_job.idempotency_key,
                    created_at=existing_job.created_at,
                    task_id=existing_job.task_id,
                    queue=race_routing_config["queue"],
                    message="Job already exists (race condition resolved)",
                    is_duplicate=True,
                )
        
        logger.error(
            "Database integrity error",
            error=str(e),
            idempotency_key=job_request.idempotency_key,
        )
        
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=JobErrorResponse(
                error=ERROR_CODE_CONFLICT,
                message="Database conflict occurred",
                details={"error": "integrity_error"},
                retryable=True,
            ).dict(),
        )
        
    except Exception as e:
        db.rollback()
        logger.error(
            "Unexpected error creating job",
            error=str(e),
            error_type=type(e).__name__,
            idempotency_key=job_request.idempotency_key,
        )
        
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=JobErrorResponse(
                error=ERROR_CODE_INTERNAL,
                message="Internal server error occurred",
                details={"error": type(e).__name__},
                retryable=True,
            ).dict(),
        )


@router.get("")
def list_jobs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0), type: str | None = None):
    with db_session() as s:
        q = s.query(Job)
        if type:
            q = q.filter(Job.type == type)
        q = q.order_by(Job.id.desc()).offset(offset).limit(limit)
        items = []
        for j in q.all():
            items.append({
                "id": j.id,
                "type": j.type,
                "status": j.status,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
                "metrics": j.metrics,
            })
        return {"items": items, "limit": limit, "offset": offset}

def _authorize_job_access(
    job: Job,
    current_user: Optional[User],
    settings: Any
) -> None:
    """
    Authorize job access for the current user.
    
    Args:
        job: The job to check access for
        current_user: The current authenticated user (optional)
        settings: Application settings
    
    Raises:
        HTTPException: If the user is not authorized to access the job
    """
    if current_user:
        # Check if user is owner
        is_owner = job.user_id == current_user.id
        
        # Check if user is admin - User model has single 'role' attribute, not 'roles' collection
        is_admin = current_user.role == UserRole.ADMIN
        
        if not (is_owner or is_admin):
            logger.warning(
                "Unauthorized job access attempt",
                job_id=job.id,
                user_id=current_user.id,
                job_owner_id=job.user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,  # Return 404 for security
                detail="İş bulunamadı / Job not found"
            )
    else:
        # No authentication - check if DEV_AUTH_BYPASS is enabled
        if not settings.DEV_AUTH_BYPASS:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="İş bulunamadı / Job not found"
            )


def _build_job_status_response(
    job: Job,
    db: Session
) -> Dict[str, Any]:
    """
    Build the job status response components.
    
    Args:
        job: The job to build response for
        db: Database session
    
    Returns:
        Dictionary containing response components:
        - progress_info: JobProgressResponse
        - artefacts_list: List[ArtefactResponse]
        - last_error: Optional[JobLastErrorResponse]
        - queue_position: Optional[int]
    """
    # Build progress information - Task 6.7: Updated to use new progress fields
    # Extract progress update timestamp for cleaner logic with safe parsing
    progress_update_str = job.metrics.get('last_progress_update') if job.metrics else None
    
    # Safely parse the timestamp, falling back to job.updated_at if invalid
    try:
        progress_updated_at = datetime.fromisoformat(progress_update_str) if progress_update_str else job.updated_at
    except (ValueError, TypeError):
        logger.warning(
            "Invalid 'last_progress_update' format in job.metrics, falling back to job.updated_at",
            job_id=job.id,
            invalid_timestamp=progress_update_str
        )
        progress_updated_at = job.updated_at
    
    # Task 6.7: Use progress_step and progress_message fields set by worker_progress_service
    progress_info = JobProgressResponse(
        percent=job.progress,
        step=(job.metrics.get('progress_step') or job.metrics.get('current_step')) if job.metrics else None,
        message=(job.metrics.get('progress_message') or job.metrics.get('last_progress_message')) if job.metrics else None,
        updated_at=progress_updated_at,
    )
    
    # Build artefacts list using list comprehension for better readability
    artefacts_list = [
        ArtefactResponse(
            id=artefact.id,
            type=artefact.type,  # Changed from 'kind' to 'type' for consistency
            s3_key=artefact.s3_key,
            sha256=artefact.sha256,
            size=artefact.size_bytes,
        )
        for artefact in job.artefacts
    ]
    
    # Build error information if present
    last_error = None
    if job.error_code and job.error_message:
        last_error = JobLastErrorResponse(
            code=job.error_code,
            message=job.error_message,
        )
    
    # Calculate queue position
    queue_position = JobQueueService.get_queue_position(db, job)
    
    return {
        "progress_info": progress_info,
        "artefacts_list": artefacts_list,
        "last_error": last_error,
        "queue_position": queue_position,
    }


def _generate_etag(
    job: Job,
    queue_position: Optional[int]
) -> str:
    """
    Generate an ETag for the job based on its current state.
    
    Args:
        job: The job to generate ETag for
        queue_position: The job's queue position
    
    Returns:
        The generated ETag string
    """
    # Include: status, progress, artefacts count, last error, queue position, metrics
    etag_components = [
        str(job.id),
        job.status.value,
        str(job.progress),
        str(len(job.artefacts)),
        str(job.error_code) if job.error_code else "none",
        str(queue_position) if queue_position is not None else "none",
        job.updated_at.isoformat() if job.updated_at else "",
        json.dumps(job.metrics, sort_keys=True) if job.metrics else "{}",
    ]
    
    etag_content = "|".join(etag_components)
    return f'W/"{hashlib.md5(etag_content.encode()).hexdigest()}"'


def _handle_etag_validation(
    request: Request,
    response: Response,
    etag: str
) -> Optional[Response]:
    """
    Handle ETag validation for conditional requests.
    
    Args:
        request: The incoming request
        response: The response object to set headers on
        etag: The generated ETag
    
    Returns:
        304 Response if ETag matches, None otherwise
    """
    # Check If-None-Match header
    if_none_match = request.headers.get("If-None-Match")
    if if_none_match and if_none_match == etag:
        # Return 304 Not Modified
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    
    # Set ETag header
    response.headers["ETag"] = etag
    
    # Set Cache-Control for short polling interval
    response.headers["Cache-Control"] = "private, max-age=1"
    
    return None


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    responses={
        200: {"model": JobStatusResponse, "description": "Job details with progress and queue position"},
        304: {"description": "Not Modified - ETag matches"},
        404: {"description": "Job not found or unauthorized"},
    }
)
async def get_job_status(
    job_id: int,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
) -> JobStatusResponse:
    """
    Get job status with progress and queue position - Task 6.5.
    
    Returns comprehensive job details including:
    - Current status and progress (percent, step, message)
    - Execution attempts and cancellation status
    - Generated artefacts with S3 keys and checksums
    - Last error information if failed
    - Queue position for pending/queued jobs
    
    Features:
    - Authorization: Owner or admin only
    - ETag support for efficient polling
    - Progress updates visible within 1s
    - Queue position calculation
    
    İş durumu ve ilerleme bilgisini getir.
    """
    
    # Fetch job with relationships - eagerly load artefacts to prevent N+1 queries
    job = db.execute(select(Job).options(joinedload(Job.artefacts)).where(Job.id == job_id)).scalar_one_or_none()
    
    if not job:
        logger.warning(
            "Job not found",
            job_id=job_id,
            user_id=getattr(current_user, "id", None),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="İş bulunamadı / Job not found"
        )
    
    # Authorization check - extracted to helper function for clarity
    _authorize_job_access(job, current_user, settings)
    
    # Build response components - extracted to helper function for maintainability
    response_components = _build_job_status_response(job, db)
    
    # Generate ETag for conditional requests
    etag = _generate_etag(job, response_components["queue_position"])
    
    # Handle ETag validation and caching headers
    not_modified_response = _handle_etag_validation(request, response, etag)
    if not_modified_response:
        return not_modified_response
    
    # Build and return response
    return JobStatusResponse(
        id=job.id,
        type=job.type,
        status=job.status,
        progress=response_components["progress_info"],
        attempts=job.attempts,
        cancel_requested=job.cancel_requested,
        created_at=job.created_at,
        updated_at=job.updated_at,
        artefacts=response_components["artefacts_list"],
        last_error=response_components["last_error"],
        queue_position=response_components["queue_position"],
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


@router.post(
    "/{job_id}/cancel",
    responses={
        200: {"description": "Cancellation requested successfully (idempotent)"},
        404: {"description": "Job not found"},
        403: {"description": "Unauthorized to cancel job"},
    }
)
async def cancel_job(
    job_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Request cancellation of a job - Task 6.6.
    
    Sets jobs.cancel_requested=true and notifies workers via Redis cache.
    This endpoint is idempotent - calling it multiple times returns success.
    
    Workers check for cancellation between major steps and will:
    - Stop processing at the next check point
    - Mark job status as 'cancelled'
    - Persist final progress
    - Not retry cancelled jobs
    - Release all resources
    
    İşi iptal et (idempotent).
    """
    
    # Get job to check permissions
    job = db.query(Job).filter(Job.id == job_id).first()
    
    if not job:
        logger.warning(
            "Job not found for cancellation",
            job_id=job_id,
            user_id=getattr(current_user, "id", None),
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="İş bulunamadı / Job not found"
        )
    
    # Authorization: Owner or admin can cancel
    if current_user:
        is_owner = job.user_id == current_user.id
        is_admin = current_user.role == UserRole.ADMIN
        
        if not (is_owner or is_admin):
            logger.warning(
                "Unauthorized job cancellation attempt",
                job_id=job_id,
                user_id=current_user.id,
                job_owner_id=job.user_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Bu işi iptal etme yetkiniz yok / Unauthorized to cancel this job"
            )
    elif not settings.DEV_AUTH_BYPASS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kimlik doğrulama gerekli / Authentication required"
        )
    
    # Request cancellation through service
    result = await job_cancellation_service.request_cancellation(
        db=db,
        job_id=job_id,
        user_id=getattr(current_user, "id", None),
        reason="User requested cancellation via API",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    
    if not result["success"]:
        # This should rarely happen since we already checked job exists
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.get("error", "İş bulunamadı / Job not found")
        )
    
    # Return idempotent response
    return {
        "job_id": job_id,
        "status": result.get("status", "cancellation_requested"),
        "cancel_requested": True,
        "message": result.get("message", "İptal isteği alındı / Cancellation requested"),
        # Note: Checking both keys for backward compatibility - older code may use either key
        "already_cancelled": result.get("was_already_requested", False) or result.get("already_cancelled", False),
    }


@router.post("/queues/{name}/pause", dependencies=[Depends(require_role("admin"))])
def pause_queue(name: str):
    queue_pause(name)
    return {"queue": name, "status": "paused"}


@router.post("/queues/{name}/resume", dependencies=[Depends(require_role("admin"))])
def resume_queue(name: str):
    queue_resume(name)
    return {"queue": name, "status": "resumed"}


