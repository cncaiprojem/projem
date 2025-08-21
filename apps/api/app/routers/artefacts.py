"""
Artefact router for Task 5.7.

Implements API endpoints for artefact management with
comprehensive security, audit logging, and S3 integration.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import get_logger
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.artefact import (
    ArtefactCreate,
    ArtefactDownloadResponse,
    ArtefactListResponse,
    ArtefactResponse,
    ArtefactS3TagsResponse,
    ArtefactSearchParams,
    ArtefactStats,
    ArtefactTagRequest,
    ArtefactType,
    ArtefactUpdate,
)
from app.services.artefact_service import ArtefactService, ArtefactServiceError

logger = get_logger(__name__)

router = APIRouter(
    prefix="/artefacts",
    tags=["artefacts"],
    responses={
        401: {"description": "Kimlik doğrulama gerekli"},
        403: {"description": "Yetkisiz erişim"},
        404: {"description": "Artefact bulunamadı"},
    },
)


@router.post(
    "",
    response_model=ArtefactResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new artefact",
    description="Create a new artefact record with S3 tagging and audit logging",
)
async def create_artefact(
    artefact_data: ArtefactCreate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArtefactResponse:
    """
    Create a new artefact.
    
    Task 5.7 Requirements:
    - Persist artefact metadata in database
    - Apply S3 object tags
    - Handle invoice retention for type='invoice'
    - Create audit log entry
    """
    try:
        service = ArtefactService(db)
        
        # Override created_by with current user
        artefact_data.created_by = current_user.id
        
        # Get client info for audit
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")
        
        artefact = await service.create_artefact(
            artefact_data=artefact_data,
            user_id=current_user.id,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        
        return ArtefactResponse.model_validate(artefact)
        
    except ArtefactServiceError as e:
        logger.warning(
            "Artefact creation failed",
            error=e.message,
            code=e.code,
            user_id=current_user.id,
        )
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "code": e.code,
                "message": e.turkish_message,
                "details": e.details,
            },
        )
    except Exception as e:
        logger.error(
            "Unexpected error creating artefact",
            error=str(e),
            user_id=current_user.id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "INTERNAL_ERROR",
                "message": "Artefact oluşturulurken beklenmeyen hata",
            },
        )


@router.get(
    "/{artefact_id}",
    response_model=ArtefactResponse,
    summary="Get artefact by ID",
    description="Get artefact details with access control",
)
async def get_artefact(
    artefact_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArtefactResponse:
    """
    Get an artefact by ID.
    
    Access control: User must own the job or be the creator.
    """
    try:
        service = ArtefactService(db)
        artefact = await service.get_artefact(
            artefact_id=artefact_id,
            user_id=current_user.id,
            check_access=True,
        )
        
        return ArtefactResponse.model_validate(artefact)
        
    except ArtefactServiceError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "code": e.code,
                "message": e.turkish_message,
            },
        )


@router.get(
    "/{artefact_id}/download",
    response_model=ArtefactDownloadResponse,
    summary="Get download URL for artefact",
    description="Generate presigned download URL with audit logging",
)
async def get_artefact_download_url(
    artefact_id: int,
    request: Request,
    expires_in: int = Query(3600, ge=60, le=86400, description="URL expiration in seconds"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArtefactDownloadResponse:
    """
    Generate presigned download URL for an artefact.
    
    Task 5.7 Requirements:
    - Enforce authorization checks
    - Audit every presigned URL issuance
    - Never expose direct S3 keys
    """
    try:
        service = ArtefactService(db)
        
        # Get client info for audit
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")
        
        presigned_url, artefact = await service.generate_download_url(
            artefact_id=artefact_id,
            user_id=current_user.id,
            expires_in=expires_in,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        
        # Extract filename from S3 key
        filename = artefact.s3_key.split("/")[-1]
        
        return ArtefactDownloadResponse(
            download_url=presigned_url,
            expires_in=expires_in,
            artefact_id=artefact.id,
            filename=filename,
            size_bytes=artefact.size_bytes,
            mime_type=artefact.mime_type,
            sha256=artefact.sha256,
        )
        
    except ArtefactServiceError as e:
        logger.warning(
            "Download URL generation failed",
            artefact_id=artefact_id,
            error=e.message,
            code=e.code,
            user_id=current_user.id,
        )
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "code": e.code,
                "message": e.turkish_message,
            },
        )


@router.get(
    "",
    response_model=ArtefactListResponse,
    summary="Search artefacts",
    description="Search and list artefacts with filters",
)
async def search_artefacts(
    job_id: Optional[int] = Query(None, description="Filter by job ID"),
    type: Optional[ArtefactType] = Query(None, description="Filter by type"),
    machine_id: Optional[int] = Query(None, description="Filter by machine ID"),
    post_processor: Optional[str] = Query(None, description="Filter by post-processor"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArtefactListResponse:
    """
    Search artefacts with filters and pagination.
    
    Only returns artefacts the user has access to.
    """
    try:
        service = ArtefactService(db)
        
        params = ArtefactSearchParams(
            job_id=job_id,
            type=type,
            machine_id=machine_id,
            post_processor=post_processor,
            page=page,
            per_page=per_page,
        )
        
        artefacts, total_count = await service.search_artefacts(
            params=params,
            user_id=current_user.id,
        )
        
        items = [ArtefactResponse.model_validate(a) for a in artefacts]
        
        return ArtefactListResponse(
            items=items,
            total=total_count,
            page=page,
            per_page=per_page,
            has_next=(page * per_page) < total_count,
            has_prev=page > 1,
        )
        
    except Exception as e:
        logger.error(
            "Search artefacts failed",
            error=str(e),
            user_id=current_user.id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "SEARCH_ERROR",
                "message": "Artefact araması başarısız",
            },
        )


@router.get(
    "/stats/summary",
    response_model=ArtefactStats,
    summary="Get artefact statistics",
    description="Get statistics about artefacts",
)
async def get_artefact_stats(
    job_id: Optional[int] = Query(None, description="Filter stats by job ID"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArtefactStats:
    """
    Get statistics about artefacts.
    
    Returns aggregated stats for artefacts the user has access to.
    """
    try:
        service = ArtefactService(db)
        stats = await service.get_artefact_stats(
            user_id=current_user.id,
            job_id=job_id,
        )
        
        return stats
        
    except Exception as e:
        logger.error(
            "Get artefact stats failed",
            error=str(e),
            user_id=current_user.id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "STATS_ERROR",
                "message": "İstatistikler alınamadı",
            },
        )


@router.patch(
    "/{artefact_id}",
    response_model=ArtefactResponse,
    summary="Update artefact metadata",
    description="Update artefact metadata fields",
)
async def update_artefact(
    artefact_id: int,
    update_data: ArtefactUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ArtefactResponse:
    """
    Update artefact metadata.
    
    Only certain fields can be updated after creation.
    """
    try:
        service = ArtefactService(db)
        
        # Get artefact with access check
        artefact = await service.get_artefact(
            artefact_id=artefact_id,
            user_id=current_user.id,
            check_access=True,
        )
        
        # Update allowed fields
        if update_data.machine_id is not None:
            artefact.machine_id = update_data.machine_id
        
        if update_data.post_processor is not None:
            artefact.post_processor = update_data.post_processor
        
        if update_data.meta is not None:
            if artefact.meta is None:
                artefact.meta = {}
            artefact.meta.update(update_data.meta)
        
        db.commit()
        db.refresh(artefact)
        
        logger.info(
            "Artefact updated",
            artefact_id=artefact_id,
            user_id=current_user.id,
        )
        
        return ArtefactResponse.model_validate(artefact)
        
    except ArtefactServiceError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "code": e.code,
                "message": e.turkish_message,
            },
        )
    except Exception as e:
        logger.error(
            "Update artefact failed",
            artefact_id=artefact_id,
            error=str(e),
            user_id=current_user.id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "UPDATE_ERROR",
                "message": "Artefact güncellenemedi",
            },
        )


@router.delete(
    "/{artefact_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an artefact",
    description="Soft delete an artefact (invoices cannot be deleted)",
)
async def delete_artefact(
    artefact_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete an artefact (soft delete).
    
    Invoices cannot be deleted due to legal requirements.
    """
    try:
        service = ArtefactService(db)
        
        # Get client info for audit
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")
        
        await service.delete_artefact(
            artefact_id=artefact_id,
            user_id=current_user.id,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        
    except ArtefactServiceError as e:
        logger.warning(
            "Artefact deletion failed",
            artefact_id=artefact_id,
            error=e.message,
            code=e.code,
            user_id=current_user.id,
        )
        raise HTTPException(
            status_code=e.status_code,
            detail={
                "code": e.code,
                "message": e.turkish_message,
            },
        )


# Export router
__all__ = ["router"]