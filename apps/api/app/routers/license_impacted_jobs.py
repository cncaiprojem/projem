"""
Task 4.9: Admin endpoint for viewing jobs impacted by license expiry.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..db import get_db
from ..middleware.jwt_middleware import AuthenticatedUser, get_current_user
from ..models.license import License
from ..services.job_cancellation_service import job_cancellation_service
from ..services.rbac_service import rbac_business_service

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/licenses", tags=["licenses"])


@router.get("/{license_id}/impacted-jobs")
async def get_impacted_jobs(
    license_id: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Get jobs impacted by license expiry (Task 4.9).
    
    **Admin-only endpoint** that shows:
    - Jobs cancelled due to license expiry
    - Jobs with cancel_requested flag set
    - Current status of affected jobs
    
    **Response includes:**
    - Job IDs and types
    - Current status and progress
    - Cancellation reason
    - Timestamps
    """

    operation_id = str(uuid.uuid4())

    try:
        # Admin-only endpoint
        is_admin = rbac_business_service.has_any_role(current_user, ["admin", "super_admin"])

        if not is_admin:
            logger.warning(
                "Non-admin user attempted to access impacted jobs",
                extra={
                    "operation": "impacted_jobs_forbidden",
                    "user_id": current_user.id,
                    "license_id": license_id,
                    "operation_id": operation_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "FORBIDDEN",
                    "message": "Admin access required",
                    "message_tr": "Yönetici erişimi gerekli",
                }
            )

        # Verify license exists
        license = db.query(License).filter(License.id == license_id).first()
        if not license:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "NOT_FOUND",
                    "message": "License not found",
                    "message_tr": "Lisans bulunamadı",
                }
            )

        # Get impacted jobs
        impacted_jobs = job_cancellation_service.get_impacted_jobs_for_license(
            db=db,
            license_id=license_id
        )

        logger.info(
            "Impacted jobs retrieved",
            extra={
                "operation": "impacted_jobs_retrieved",
                "user_id": current_user.id,
                "license_id": license_id,
                "job_count": len(impacted_jobs),
                "operation_id": operation_id,
            },
        )

        return {
            "license_id": license_id,
            "user_id": license.user_id,
            "license_status": license.status,
            "impacted_jobs": impacted_jobs,
            "total_count": len(impacted_jobs),
            "message": "Impacted jobs retrieved successfully",
            "message_tr": "Etkilenen işler başarıyla alındı",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to retrieve impacted jobs",
            exc_info=True,
            extra={
                "operation": "impacted_jobs_failed",
                "user_id": current_user.id,
                "license_id": license_id,
                "operation_id": operation_id,
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_ERROR",
                "message": "Failed to retrieve impacted jobs",
                "message_tr": "Etkilenen işler alınamadı",
            }
        )
