"""
License management endpoints with idempotency support.
Task 4.11: Implements license assignment and extension with exactly-once semantics.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..db import get_db
from ..middleware.idempotency import require_idempotency
from ..middleware.jwt_middleware import AuthenticatedUser, get_current_user
from ..models.enums import LicenseStatus, LicenseType
from ..models.license import License
from ..models.user import User
from ..services.rbac_service import rbac_business_service

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/licenses", tags=["licenses"])


class LicenseAssignRequest(BaseModel):
    """Request to assign a new license to a user."""
    user_id: int = Field(..., description="User ID to assign license to")
    plan: LicenseType = Field(..., description="License plan type")
    seats: int = Field(1, ge=1, description="Number of seats")
    duration_days: int = Field(30, ge=1, description="License duration in days")
    auto_renew: bool = Field(False, description="Auto-renewal setting")
    features: dict = Field(default_factory=dict, description="Additional features")


class LicenseExtendRequest(BaseModel):
    """Request to extend an existing license."""
    license_id: int = Field(..., description="License ID to extend")
    extension_days: int = Field(30, ge=1, description="Days to extend")


class LicenseResponse(BaseModel):
    """License response model."""
    id: int
    user_id: int
    plan: str
    status: str
    seats: int
    features: dict
    starts_at: datetime
    ends_at: datetime
    auto_renew: bool
    is_active: bool
    days_remaining: int
    message: str
    message_tr: str


@router.post("/assign", response_model=LicenseResponse)
@require_idempotency(ttl_hours=24, required=True)
async def assign_license(
    request_data: LicenseAssignRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Assign a new license to a user (idempotent operation).
    
    **Requires Idempotency-Key header for exactly-once semantics.**
    
    Admin-only endpoint that:
    - Creates a new license for the specified user
    - Ensures only one active license per user
    - Sets license period based on duration_days
    
    Returns the created license details.
    """
    operation_id = str(uuid.uuid4())

    try:
        # Admin-only endpoint
        is_admin = rbac_business_service.has_any_role(current_user, ["admin", "super_admin"])

        if not is_admin:
            logger.warning(
                "Non-admin user attempted to assign license",
                extra={
                    "operation": "license_assign_forbidden",
                    "user_id": current_user.id,
                    "target_user_id": request_data.user_id,
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

        # Verify target user exists
        target_user = db.query(User).filter(User.id == request_data.user_id).first()
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "USER_NOT_FOUND",
                    "message": "User not found",
                    "message_tr": "Kullanıcı bulunamadı",
                }
            )

        # Check for existing active license (will be blocked by unique constraint)
        existing_active = db.query(License).filter(
            License.user_id == request_data.user_id,
            License.status == LicenseStatus.ACTIVE
        ).first()

        if existing_active:
            logger.warning(
                "User already has active license",
                extra={
                    "operation": "license_assign_duplicate",
                    "user_id": request_data.user_id,
                    "existing_license_id": existing_active.id,
                    "operation_id": operation_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "ACTIVE_LICENSE_EXISTS",
                    "message": "User already has an active license",
                    "message_tr": "Kullanıcının zaten aktif bir lisansı var",
                    "existing_license_id": existing_active.id,
                }
            )

        # Create new license
        now = datetime.now(UTC)
        ends_at = now + timedelta(days=request_data.duration_days)

        new_license = License(
            user_id=request_data.user_id,
            plan=request_data.plan,
            status=LicenseStatus.ACTIVE,
            seats=request_data.seats,
            features=request_data.features,
            starts_at=now,
            ends_at=ends_at,
            auto_renew=request_data.auto_renew
        )

        try:
            db.add(new_license)
            db.commit()
            db.refresh(new_license)

            logger.info(
                "License assigned successfully",
                extra={
                    "operation": "license_assigned",
                    "admin_id": current_user.id,
                    "user_id": request_data.user_id,
                    "license_id": new_license.id,
                    "plan": request_data.plan.value,
                    "duration_days": request_data.duration_days,
                    "operation_id": operation_id,
                },
            )

            return LicenseResponse(
                id=new_license.id,
                user_id=new_license.user_id,
                plan=new_license.plan.value,
                status=new_license.status.value,
                seats=new_license.seats,
                features=new_license.features,
                starts_at=new_license.starts_at,
                ends_at=new_license.ends_at,
                auto_renew=new_license.auto_renew,
                is_active=new_license.is_active,
                days_remaining=new_license.days_remaining,
                message="License assigned successfully",
                message_tr="Lisans başarıyla atandı"
            )

        except IntegrityError as e:
            db.rollback()

            # Check if it's the unique constraint violation
            if "uq_licenses_one_active_per_user" in str(e):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "ACTIVE_LICENSE_EXISTS",
                        "message": "User already has an active license",
                        "message_tr": "Kullanıcının zaten aktif bir lisansı var",
                    }
                )
            else:
                raise

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to assign license",
            exc_info=True,
            extra={
                "operation": "license_assign_failed",
                "admin_id": current_user.id,
                "user_id": request_data.user_id,
                "operation_id": operation_id,
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_ERROR",
                "message": "Failed to assign license",
                "message_tr": "Lisans atanamadı",
            }
        )


@router.post("/extend", response_model=LicenseResponse)
@require_idempotency(ttl_hours=24, required=True)
async def extend_license(
    request_data: LicenseExtendRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Extend an existing license (idempotent operation).
    
    **Requires Idempotency-Key header for exactly-once semantics.**
    
    Admin-only endpoint that:
    - Extends the end date of an existing license
    - Works for both active and expired licenses
    - Reactivates expired licenses
    
    Returns the updated license details.
    """
    operation_id = str(uuid.uuid4())

    try:
        # Admin-only endpoint
        is_admin = rbac_business_service.has_any_role(current_user, ["admin", "super_admin"])

        if not is_admin:
            logger.warning(
                "Non-admin user attempted to extend license",
                extra={
                    "operation": "license_extend_forbidden",
                    "user_id": current_user.id,
                    "license_id": request_data.license_id,
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

        # Get the license
        license = db.query(License).filter(
            License.id == request_data.license_id
        ).first()

        if not license:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "error": "LICENSE_NOT_FOUND",
                    "message": "License not found",
                    "message_tr": "Lisans bulunamadı",
                }
            )

        # Extend the license
        old_ends_at = license.ends_at

        # If license is expired, extend from today
        # Otherwise, extend from current end date
        now = datetime.now(UTC)
        if license.ends_at < now:
            # License is expired, extend from today
            license.ends_at = now + timedelta(days=request_data.extension_days)
            # Reactivate if it was expired
            if license.status == LicenseStatus.EXPIRED:
                license.status = LicenseStatus.ACTIVE
        else:
            # License is still valid, extend from end date
            license.ends_at = license.ends_at + timedelta(days=request_data.extension_days)

        db.commit()
        db.refresh(license)

        logger.info(
            "License extended successfully",
            extra={
                "operation": "license_extended",
                "admin_id": current_user.id,
                "license_id": license.id,
                "user_id": license.user_id,
                "old_ends_at": old_ends_at.isoformat(),
                "new_ends_at": license.ends_at.isoformat(),
                "extension_days": request_data.extension_days,
                "operation_id": operation_id,
            },
        )

        return LicenseResponse(
            id=license.id,
            user_id=license.user_id,
            plan=license.plan.value,
            status=license.status.value,
            seats=license.seats,
            features=license.features,
            starts_at=license.starts_at,
            ends_at=license.ends_at,
            auto_renew=license.auto_renew,
            is_active=license.is_active,
            days_remaining=license.days_remaining,
            message="License extended successfully",
            message_tr="Lisans başarıyla uzatıldı"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to extend license",
            exc_info=True,
            extra={
                "operation": "license_extend_failed",
                "admin_id": current_user.id,
                "license_id": request_data.license_id,
                "operation_id": operation_id,
                "error_type": type(e).__name__,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": "INTERNAL_ERROR",
                "message": "Failed to extend license",
                "message_tr": "Lisans uzatılamadı",
            }
        )
