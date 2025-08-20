"""
Ultra-Enterprise File Upload/Download Router for Task 5.3

FastAPI router implementing:
- POST /files/upload/init - Initialize upload with presigned URL
- POST /files/upload/finalize - Finalize and verify upload
- GET /files/{file_id} - Get download URL with authorization
"""

from __future__ import annotations

import uuid
from typing import Optional, Dict, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
    HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_429_TOO_MANY_REQUESTS,
    HTTP_500_INTERNAL_SERVER_ERROR,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.minio_config import get_minio_client
from app.models.user import User
from app.schemas.file_upload import (
    UploadInitRequest,
    UploadInitResponse,
    UploadFinalizeRequest,
    UploadFinalizeResponse,
    FileDownloadResponse,
    UploadError,
    UploadErrorCode,
)
from app.services.file_service import (
    FileService,
    FileServiceError,
    get_file_service,
)
from app.core.rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)

# Create router
router = APIRouter(
    prefix="/files",
    tags=["files"],
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
        429: {"description": "Rate limited"},
        500: {"description": "Internal server error"},
    },
)

# Rate limiter for upload operations
upload_rate_limiter = RateLimiter(
    max_requests=10,  # 10 uploads
    window_seconds=60,  # per minute
)

# Rate limiter for download operations
download_rate_limiter = RateLimiter(
    max_requests=60,  # 60 downloads
    window_seconds=60,  # per minute
)


@router.post(
    "/upload/init",
    response_model=UploadInitResponse,
    status_code=HTTP_201_CREATED,
    summary="Initialize file upload",
    description="Initialize file upload with presigned PUT URL (Task 5.3)",
    responses={
        201: {"description": "Upload initialized successfully"},
        400: {"description": "Invalid input", "model": UploadError},
        401: {"description": "Unauthorized", "model": UploadError},
        413: {"description": "Payload too large", "model": UploadError},
        415: {"description": "Unsupported media type", "model": UploadError},
        429: {"description": "Rate limited", "model": UploadError},
    },
)
def init_upload(
    request: UploadInitRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadInitResponse:
    """
    Initialize file upload with presigned URL.
    
    Task 5.3 Requirements:
    - Validate inputs: size ≤ 200MB, type/mime allowed list
    - Generate server-side key: artefacts/{job_id}/{uuid}.{ext}
    - Presign PUT URL (TTL 5m), optionally bind client IP
    - Include conditions for content-type and content-length-range
    - Include tagging for job_id/machine/post
    
    Args:
        request: Upload initialization request
        req: FastAPI request for client IP
        db: Database session
        current_user: Authenticated user
        
    Returns:
        UploadInitResponse with presigned URL
        
    Raises:
        HTTPException: On validation or generation failure
    """
    try:
        # Check rate limit
        client_ip = req.client.host if req.client else None
        user_key = f"upload:{current_user.id}"
        
        if not upload_rate_limiter.check_rate_limit(user_key):
            logger.warning(
                "Upload rate limit exceeded",
                user_id=str(current_user.id),
                client_ip=client_ip,
            )
            raise HTTPException(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                detail=UploadError(
                    code=UploadErrorCode.RATE_LIMITED,
                    message="Too many upload requests",
                    turkish_message="Çok fazla yükleme isteği",
                    details={"retry_after": 60},
                ).dict(),
            )
        
        # Set client IP in request
        request.client_ip = client_ip
        
        # Initialize file service
        file_service = get_file_service(db=db)
        
        # Call service method - FileService.init_upload is NOT async
        response = file_service.init_upload(
            request=request,
            user_id=str(current_user.id),
            client_ip=client_ip,
        )
        
        logger.info(
            "Upload initialized",
            user_id=str(current_user.id),
            upload_id=response.upload_id,
            object_key=response.key,
            size=request.size,
            type=request.type,
        )
        
        return response
        
    except FileServiceError as e:
        logger.error(
            "Upload initialization failed",
            error_code=e.code,
            error_message=e.message,
            user_id=str(current_user.id),
        )
        
        # Map error codes to HTTP status codes
        status_map = {
            UploadErrorCode.INVALID_INPUT: HTTP_400_BAD_REQUEST,
            UploadErrorCode.UNAUTHORIZED: HTTP_401_UNAUTHORIZED,
            UploadErrorCode.UNSUPPORTED_MEDIA_TYPE: HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            UploadErrorCode.PAYLOAD_TOO_LARGE: HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            UploadErrorCode.RATE_LIMITED: HTTP_429_TOO_MANY_REQUESTS,
            UploadErrorCode.STORAGE_ERROR: HTTP_500_INTERNAL_SERVER_ERROR,
        }
        
        raise HTTPException(
            status_code=status_map.get(e.code, HTTP_400_BAD_REQUEST),
            detail=UploadError(
                code=e.code,
                message=e.message,
                turkish_message=e.turkish_message,
                details=e.details,
                request_id=str(uuid.uuid4()),
            ).dict(),
        )
        
    except Exception as e:
        logger.error(
            "Unexpected error during upload initialization",
            error=str(e),
            exc_info=True,
            user_id=str(current_user.id),
        )
        
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=UploadError(
                code=UploadErrorCode.STORAGE_ERROR,
                message="Internal server error",
                turkish_message="Sunucu hatası",
                request_id=str(uuid.uuid4()),
            ).dict(),
        )


@router.post(
    "/upload/finalize",
    response_model=UploadFinalizeResponse,
    status_code=HTTP_200_OK,
    summary="Finalize file upload",
    description="Finalize upload and verify integrity (Task 5.3)",
    responses={
        200: {"description": "Upload finalized successfully"},
        404: {"description": "Upload not found", "model": UploadError},
        409: {"description": "Upload incomplete", "model": UploadError},
        413: {"description": "Size mismatch", "model": UploadError},
        422: {"description": "Hash mismatch", "model": UploadError},
        503: {"description": "Service unavailable", "model": UploadError},
    },
)
def finalize_upload(
    request: UploadFinalizeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> UploadFinalizeResponse:
    """
    Finalize file upload and verify integrity.
    
    Task 5.3 Requirements:
    - Look up expected metadata from init
    - Stream-verify existence and SHA256 (Task 5.5)
    - Optional malware scan (Task 5.6)
    - Persist artefact (Task 5.7)
    
    Args:
        request: Upload finalization request
        db: Database session
        current_user: Authenticated user
        
    Returns:
        UploadFinalizeResponse with verification results
        
    Raises:
        HTTPException: On verification failure
    """
    try:
        # Initialize file service
        file_service = get_file_service(db=db)
        
        # Call service method - FileService.finalize_upload is NOT async
        response = file_service.finalize_upload(
            request=request,
            user_id=str(current_user.id),
        )
        
        logger.info(
            "Upload finalized",
            user_id=str(current_user.id),
            object_key=response.object_key,
            size=response.size,
            sha256=response.sha256,
        )
        
        return response
        
    except FileServiceError as e:
        logger.error(
            "Upload finalization failed",
            error_code=e.code,
            error_message=e.message,
            user_id=str(current_user.id),
        )
        
        # Map error codes to HTTP status codes
        status_map = {
            UploadErrorCode.NOT_FOUND: HTTP_404_NOT_FOUND,
            UploadErrorCode.UPLOAD_INCOMPLETE: HTTP_409_CONFLICT,
            UploadErrorCode.PAYLOAD_TOO_LARGE: HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            UploadErrorCode.HASH_MISMATCH: HTTP_422_UNPROCESSABLE_ENTITY,
            UploadErrorCode.MALWARE_DETECTED: HTTP_422_UNPROCESSABLE_ENTITY,
            UploadErrorCode.SCAN_UNAVAILABLE: HTTP_503_SERVICE_UNAVAILABLE,
            UploadErrorCode.STORAGE_ERROR: HTTP_500_INTERNAL_SERVER_ERROR,
        }
        
        raise HTTPException(
            status_code=status_map.get(e.code, HTTP_400_BAD_REQUEST),
            detail=UploadError(
                code=e.code,
                message=e.message,
                turkish_message=e.turkish_message,
                details=e.details,
                request_id=str(uuid.uuid4()),
            ).dict(),
        )
        
    except Exception as e:
        logger.error(
            "Unexpected error during upload finalization",
            error=str(e),
            exc_info=True,
            user_id=str(current_user.id),
        )
        
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=UploadError(
                code=UploadErrorCode.STORAGE_ERROR,
                message="Internal server error",
                turkish_message="Sunucu hatası",
                request_id=str(uuid.uuid4()),
            ).dict(),
        )


@router.get(
    "/{file_id}",
    response_model=FileDownloadResponse,
    status_code=HTTP_200_OK,
    summary="Get file download URL",
    description="Generate presigned GET URL for file download (Task 5.3)",
    responses={
        200: {"description": "Download URL generated"},
        401: {"description": "Unauthorized", "model": UploadError},
        403: {"description": "Access denied", "model": UploadError},
        404: {"description": "File not found", "model": UploadError},
        429: {"description": "Rate limited", "model": UploadError},
    },
)
def get_download_url(
    file_id: str = Path(
        ...,
        description="File ID (UUID) or object key",
        example="550e8400-e29b-41d4-a716-446655440000",
    ),
    version_id: Optional[str] = Query(
        None,
        description="Specific version to download",
    ),
    req: Request = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileDownloadResponse:
    """
    Generate presigned GET URL for file download.
    
    Task 5.3 Requirements:
    - Authorize access by artefact ownership/role
    - Log audit trail
    - Return presigned GET URL (TTL 2m)
    - For invoices ensure object lock is respected
    
    Args:
        file_id: File ID (UUID) or object key
        version_id: Optional specific version
        req: FastAPI request
        db: Database session
        current_user: Authenticated user
        
    Returns:
        FileDownloadResponse with presigned URL
        
    Raises:
        HTTPException: On authorization or generation failure
    """
    try:
        # Check rate limit
        user_key = f"download:{current_user.id}"
        
        if not download_rate_limiter.check_rate_limit(user_key):
            logger.warning(
                "Download rate limit exceeded",
                user_id=str(current_user.id),
                file_id=file_id,
            )
            raise HTTPException(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                detail=UploadError(
                    code=UploadErrorCode.RATE_LIMITED,
                    message="Too many download requests",
                    turkish_message="Çok fazla indirme isteği",
                    details={"retry_after": 60},
                ).dict(),
            )
        
        # Initialize file service
        file_service = get_file_service(db=db)
        
        # Call service method - FileService.get_download_url is NOT async
        response = file_service.get_download_url(
            file_id=file_id,
            user_id=str(current_user.id),
            version_id=version_id,
        )
        
        logger.info(
            "Download URL generated",
            user_id=str(current_user.id),
            file_id=file_id,
            version_id=version_id,
            expires_in=response.expires_in,
        )
        
        return response
        
    except FileServiceError as e:
        logger.error(
            "Download URL generation failed",
            error_code=e.code,
            error_message=e.message,
            user_id=str(current_user.id),
            file_id=file_id,
        )
        
        # Map error codes to HTTP status codes
        status_map = {
            UploadErrorCode.UNAUTHORIZED: HTTP_401_UNAUTHORIZED,
            UploadErrorCode.FORBIDDEN: HTTP_403_FORBIDDEN,
            UploadErrorCode.NOT_FOUND: HTTP_404_NOT_FOUND,
            UploadErrorCode.STORAGE_ERROR: HTTP_500_INTERNAL_SERVER_ERROR,
        }
        
        raise HTTPException(
            status_code=status_map.get(e.code, HTTP_400_BAD_REQUEST),
            detail=UploadError(
                code=e.code,
                message=e.message,
                turkish_message=e.turkish_message,
                details=e.details,
                request_id=str(uuid.uuid4()),
            ).dict(),
        )
        
    except Exception as e:
        logger.error(
            "Unexpected error during download URL generation",
            error=str(e),
            exc_info=True,
            user_id=str(current_user.id),
            file_id=file_id,
        )
        
        raise HTTPException(
            status_code=HTTP_500_INTERNAL_SERVER_ERROR,
            detail=UploadError(
                code=UploadErrorCode.STORAGE_ERROR,
                message="Internal server error",
                turkish_message="Sunucu hatası",
                request_id=str(uuid.uuid4()),
            ).dict(),
        )


# Health check endpoint for file service
@router.get(
    "/health",
    status_code=HTTP_200_OK,
    summary="File service health check",
    description="Check if file service is operational",
    include_in_schema=False,
)
def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for file service.
    
    Returns:
        Dict with service status
    """
    try:
        # Try to get MinIO client
        client = get_minio_client()
        
        # Check if we can list buckets (basic connectivity test)
        buckets = client.list_buckets()
        
        return {
            "status": "healthy",
            "service": "file-service",
            "storage": "connected",
            "buckets": len(buckets),
        }
        
    except Exception as e:
        logger.error(
            "File service health check failed",
            error=str(e),
        )
        
        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "unhealthy",
                "service": "file-service",
                "error": str(e),
            },
        )


__all__ = [
    "router",
]