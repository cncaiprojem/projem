"""
Enhanced Artefact Router for Task 7.11.

API endpoints for comprehensive artefact management with:
- File upload with versioning
- Presigned URL generation (GET and HEAD)
- Garbage collection and deletion
- Turkish localization
- Enterprise security
"""

from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.artefact import (
    ArtefactDownloadResponse,
    ArtefactResponse,
)
from app.services.artefact_service_v2 import (
    ArtefactServiceV2,
    ArtefactServiceV2Error,
    TURKISH_MESSAGES,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v2/artefacts",
    tags=["artefacts-v2"],
    responses={
        401: {"description": "Kimlik doğrulama gerekli"},
        403: {"description": "Yetkisiz erişim"},
        404: {"description": "Artefact bulunamadı"},
        500: {"description": "Sunucu hatası"},
    },
)


@router.post(
    "/upload",
    response_model=ArtefactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file and create artefact",
    description="Upload a file to S3/MinIO and create artefact record with versioning",
)
async def upload_artefact(
    request: Request,
    file: UploadFile = File(..., description="File to upload"),
    job_id: int = Form(..., description="Associated job ID"),
    artefact_type: str = Form(..., description="Type of artefact (model, gcode, report, etc.)"),
    machine_id: Optional[int] = Form(None, description="Optional machine ID"),
    post_processor: Optional[str] = Form(None, description="Optional post-processor"),
    exporter_version: Optional[str] = Form(None, description="Version of exporter/converter"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Upload a file and create an artefact with Task 7.11 features.
    
    Features:
    - Automatic content type detection
    - SHA256 computation
    - S3 versioning support
    - Comprehensive metadata tracking
    - Turkish error messages
    """
    service = ArtefactServiceV2(db)
    
    # Get client info for audit
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    
    try:
        # FastAPI's UploadFile already provides efficient streaming via SpooledTemporaryFile
        # It automatically handles memory/disk switching based on file size
        # We can directly use the file.file attribute which is a SpooledTemporaryFile
        
        # Upload and create artefact - pass file.file directly
        # The service will handle it in a thread pool to avoid blocking
        artefact = await service.upload_artefact(
            file_obj=file.file,  # Use FastAPI's built-in SpooledTemporaryFile
            job_id=job_id,
            artefact_type=artefact_type,
            filename=file.filename,
            user=current_user,  # Pass User object directly to avoid redundant query
            machine_id=machine_id,
            post_processor=post_processor,
            exporter_version=exporter_version,
            metadata={
                "original_filename": file.filename,
                "content_type": file.content_type,
                "upload_size": file.size if file.size else None,
            },
            ip_address=client_ip,
            user_agent=user_agent,
        )
        
        return ArtefactResponse.model_validate(artefact)
        
    except ArtefactServiceV2Error as e:
        logger.error(
            "Artefact upload failed",
            error=str(e),
            code=e.code,
            user_id=current_user.id,
        )
        
        # Return Turkish message if Accept-Language header indicates Turkish
        accept_language = request.headers.get("Accept-Language", "")
        if "tr" in accept_language.lower():
            message = e.turkish_message
        else:
            message = e.message
            
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "code": e.code,
                "message": message,
                "details": e.details,
            },
        )
    except Exception as e:
        logger.error(
            "Unexpected error during upload",
            error=str(e),
            user_id=current_user.id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Upload failed due to unexpected error",
            },
        )


@router.get(
    "/{artefact_id}/download",
    response_model=ArtefactDownloadResponse,
    summary="Generate presigned download URL",
    description="Generate a version-specific presigned URL for downloading an artefact",
)
async def generate_download_url(
    request: Request,
    artefact_id: int,
    expires_in: Optional[int] = Query(
        900,
        ge=1,
        le=86400,
        description="URL expiration in seconds (max 24 hours)",
    ),
    inline: Optional[bool] = Query(
        None,
        description="Force inline display (true) or download (false)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a presigned download URL for an artefact.
    
    Features:
    - Version-specific URLs
    - Configurable expiration (15 min default, 24 hour max)
    - Optional content disposition override
    - Audit logging
    """
    service = ArtefactServiceV2(db)
    
    # Get client info for audit
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    
    try:
        # Determine content disposition based on inline parameter
        content_disposition = None
        if inline is not None:
            if inline:
                content_disposition = "inline"
            else:
                content_disposition = "attachment"
        
        # Generate presigned URL
        url, artefact = await service.generate_presigned_download_url(
            artefact_id=artefact_id,
            user_id=current_user.id,
            expires_in=expires_in,
            response_content_disposition=content_disposition,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        
        return ArtefactDownloadResponse(
            download_url=url,
            expires_in=expires_in,
            artefact=ArtefactResponse.model_validate(artefact),
        )
        
    except ArtefactServiceV2Error as e:
        # Return Turkish message if requested
        accept_language = request.headers.get("Accept-Language", "")
        if "tr" in accept_language.lower():
            message = e.turkish_message
        else:
            message = e.message
            
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "code": e.code,
                "message": message,
            },
        )


@router.head(
    "/{artefact_id}/validate",
    summary="Generate presigned HEAD URL",
    description="Generate a presigned HEAD URL to validate artefact availability",
)
async def generate_head_url(
    request: Request,
    artefact_id: int,
    expires_in: Optional[int] = Query(
        60,
        ge=1,
        le=3600,
        description="URL expiration in seconds (max 1 hour)",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate a presigned HEAD URL for validation.
    
    Use this to check if an artefact exists without downloading it.
    """
    service = ArtefactServiceV2(db)
    
    try:
        # Generate HEAD URL
        url = await service.generate_presigned_head_url(
            artefact_id=artefact_id,
            user_id=current_user.id,
            expires_in=expires_in,
        )
        
        # Return URL in header
        return {
            "X-Presigned-HEAD-URL": url,
            "X-Expires-In": str(expires_in),
        }
        
    except ArtefactServiceV2Error as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.code, "message": e.message},
        )


@router.delete(
    "/{artefact_id}",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Delete an artefact",
    description="Schedule artefact for deletion with garbage collection",
)
async def delete_artefact(
    request: Request,
    artefact_id: int,
    force: bool = Query(
        False,
        description="Force delete even for invoices",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete an artefact with async garbage collection.
    
    Features:
    - Async deletion via Celery task
    - Invoice protection (unless forced)
    - All versions deleted
    - Audit logging
    """
    service = ArtefactServiceV2(db)
    
    # Get client info for audit
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")
    
    try:
        await service.delete_artefact(
            artefact_id=artefact_id,
            user_id=current_user.id,
            force=force,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        
        # Return Turkish message if requested
        accept_language = request.headers.get("Accept-Language", "")
        if "tr" in accept_language.lower():
            message = TURKISH_MESSAGES["storage.delete.pending"]
        else:
            message = "Deletion scheduled"
            
        return {
            "status": "accepted",
            "message": message,
            "artefact_id": artefact_id,
        }
        
    except ArtefactServiceV2Error as e:
        # Return Turkish message if requested
        accept_language = request.headers.get("Accept-Language", "")
        if "tr" in accept_language.lower():
            message = e.turkish_message
        else:
            message = e.message
            
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "code": e.code,
                "message": message,
            },
        )


@router.post(
    "/jobs/{job_id}/cleanup",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Delete all artefacts for a job",
    description="Schedule deletion of all artefacts associated with a job",
    dependencies=[Depends(get_current_user)],
)
async def delete_job_artefacts(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete all artefacts for a job (CASCADE behavior).
    
    This endpoint is typically called when a job is deleted.
    All associated artefacts will be scheduled for garbage collection.
    """
    service = ArtefactServiceV2(db)
    
    # Check if user is admin (only admins can bulk delete)
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Only administrators can perform bulk deletion",
            },
        )
    
    try:
        deleted_count = await service.delete_job_artefacts(job_id)
        
        return {
            "status": "accepted",
            "message": f"{deleted_count} artefacts scheduled for deletion",
            "job_id": job_id,
            "artefacts_count": deleted_count,
        }
        
    except ArtefactServiceV2Error as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "code": e.code,
                "message": e.message,
            },
        )


@router.post(
    "/gc/retry",
    status_code=status.HTTP_200_OK,
    summary="Retry failed deletions",
    description="Retry garbage collection for failed deletions",
    dependencies=[Depends(get_current_user)],
)
async def retry_failed_deletions(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Retry failed garbage collection attempts.
    
    This endpoint should be called periodically or manually
    to retry deletions that previously failed.
    """
    # Check if user is admin
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "UNAUTHORIZED",
                "message": "Only administrators can retry failed deletions",
            },
        )
    
    service = ArtefactServiceV2(db)
    
    try:
        retry_count = await service.retry_failed_deletions()
        
        return {
            "status": "success",
            "message": f"{retry_count} deletions retried",
            "retry_count": retry_count,
        }
        
    except Exception as e:
        logger.error("Failed to retry deletions", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "RETRY_FAILED",
                "message": f"Failed to retry deletions: {str(e)}",
            },
        )


@router.get(
    "/{artefact_id}/validate-integrity",
    summary="Validate artefact integrity",
    description="Check if artefact exists and validate SHA256 integrity",
)
async def validate_artefact(
    artefact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Validate artefact integrity.
    
    Checks:
    - Artefact exists in database
    - User has access
    - SHA256 hash is valid
    - Object exists in storage (via HEAD request)
    """
    service = ArtefactServiceV2(db)
    
    try:
        is_valid = await service.validate_artefact_integrity(
            artefact_id=artefact_id,
            user_id=current_user.id,
        )
        
        return {
            "artefact_id": artefact_id,
            "valid": is_valid,
            "message": "Artefact validated successfully" if is_valid else "Validation failed",
        }
        
    except ArtefactServiceV2Error as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "code": e.code,
                "message": e.message,
            },
        )


# Export router
__all__ = ["router"]