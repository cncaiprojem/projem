"""
Task 4.2: License APIs with Ultra-Enterprise Banking Standards
Implements POST /license/assign|extend|cancel and GET /license/me
with full audit trail, KVKV compliance, and idempotency support.
"""

from datetime import datetime, timezone
from typing import Optional, Dict, Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from ..middleware.jwt_middleware import get_current_user, AuthenticatedUser
from ..db import get_db
from ..core.logging import get_logger
from ..services.rbac_service import rbac_business_service
from ..models.user import User
from ..models.enums import UserRole
from ..models.license import License
from ..services.license_service import LicenseService, LicenseStateError
from ..services.idempotency_service import IdempotencyService
from ..schemas.license import (
    LicenseAssignRequest,
    LicenseAssignResponse,
    LicenseExtendRequest,
    LicenseExtendResponse,
    LicenseCancelRequest,
    LicenseCancelResponse,
    LicenseMeResponse,
    LicenseResponse,
    LicenseErrorCodes,
    LicenseTypeValidator,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/license", tags=["license"])


def check_role(user: AuthenticatedUser, roles: list[str]) -> bool:
    """Check if user has any of the specified roles."""
    if not user or not user.role:
        return False
    return user.role.value in roles


def anonymize_ip(ip_address: str) -> str:
    """Anonymize IP address for KVKV compliance."""
    if not ip_address or ip_address == "unknown":
        return ip_address

    # Check if it's IPv6
    if ":" in ip_address:
        # IPv6 address - keep first 3 parts and mask the rest
        parts = ip_address.split(":")
        if len(parts) >= 4:
            # Keep first 3 parts, replace rest with xxxx
            return ":".join(parts[:3]) + "::xxxx"
        return ip_address
    else:
        # IPv4 address - keep first 3 octets
        parts = ip_address.split(".")
        if len(parts) == 4:
            return f"{parts[0]}.{parts[1]}.{parts[2]}.xxx"
        return ip_address


def get_client_info(request: Request) -> tuple[str, str]:
    """Extract client IP and user agent for audit purposes."""
    # Get raw IP and anonymize it for KVKV compliance
    client_ip = request.client.host if request.client else "unknown"
    client_ip = anonymize_ip(client_ip)

    user_agent = request.headers.get("user-agent", "unknown")[:200]  # Truncate for storage
    return client_ip, user_agent


def get_status_translation(
    status: str, days_remaining: Optional[int] = None
) -> tuple[str, Optional[str]]:
    """Get Turkish translation for license status with warnings."""

    status_translations = {
        "active": "aktif",
        "expired": "süresi_dolmuş",
        "canceled": "iptal_edilmiş",
        "trial": "deneme",
        "none": "yok",
    }

    status_tr = status_translations.get(status, "bilinmeyen")
    warning_message_tr = None

    # Generate warning messages based on days remaining
    if status == "active" and days_remaining is not None:
        if days_remaining <= 3:
            warning_message_tr = (
                f"Lisansınızın süresi {days_remaining} gün içinde dolacak! Lütfen yenileyin."
            )
        elif days_remaining <= 7:
            warning_message_tr = f"Lisansınızın süresi {days_remaining} gün içinde dolacak."
        elif days_remaining <= 30:
            warning_message_tr = f"Lisansınızın süresi {days_remaining} gün içinde dolacak. Yenileme işlemini planlamanızı öneririz."
    elif status == "expired":
        warning_message_tr = "Lisansınızın süresi dolmuş! Hizmetlere erişim kısıtlanabilir."
    elif status == "canceled":
        warning_message_tr = "Lisansınız iptal edilmiş. Yönetici ile iletişime geçin."
    elif status == "none":
        warning_message_tr = "Henüz bir lisansınız yok. Lütfen bir lisans satın alın."

    return status_tr, warning_message_tr


@router.post("/assign", response_model=LicenseAssignResponse)
async def assign_license(
    request_data: LicenseAssignRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Assign a new license to a user.

    **Ultra-Enterprise Features:**
    - Admin can assign to any user; user can self-assign if allowed by business rules
    - Full audit trail with Turkish KVKV compliance
    - Idempotency support with Idempotency-Key header
    - Role-based access control enforcement
    - Banking-grade error handling

    **Request Requirements:**
    - `type`: License duration ('3m', '6m', '12m')
    - `scope`: License scope configuration (features, limits)
    - `user_id`: Target user (admin only, auto-filled for self-assignment)
    - `starts_at`: Start time (optional, defaults to now)

    **Error Codes:**
    - 409 ACTIVE_LICENSE_EXISTS: User already has active license
    - 400 INVALID_TYPE: Invalid license type specified
    - 403 FORBIDDEN: Insufficient permissions
    """

    client_ip, user_agent = get_client_info(request)
    operation_id = str(uuid.uuid4())

    try:
        # Validate license type
        if not LicenseTypeValidator.validate_type(request_data.type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=LicenseErrorCodes.get_error_response(
                    LicenseErrorCodes.INVALID_TYPE,
                    {"valid_types": LicenseTypeValidator.VALID_TYPES},
                ).dict(),
            )

        # Determine target user
        target_user_id = request_data.user_id or current_user.id
        # Use rbac_business_service instead of custom role checking
        is_admin = (
            rbac_business_service.has_any_role(current_user, ["admin", "super_admin"])
            if hasattr(rbac_business_service, "has_any_role")
            else check_role(current_user, ["admin", "super_admin"])
        )

        # Authorization check
        if target_user_id != current_user.id and not is_admin:
            logger.warning(
                "Non-admin user attempted to assign license to another user",
                extra={
                    "operation": "license_assign_forbidden",
                    "user_id": current_user.id,
                    "target_user_id": target_user_id,
                    "operation_id": operation_id,
                },
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=LicenseErrorCodes.get_error_response(LicenseErrorCodes.FORBIDDEN).dict(),
            )

        # Check idempotency if key provided
        if idempotency_key:
            existing_response = await IdempotencyService.get_response(
                db, idempotency_key, current_user.id, endpoint="/api/v1/license/assign"
            )
            if existing_response:
                logger.info(f"Returning idempotent response for key {idempotency_key[:20]}...")
                return existing_response

        # Verify target user exists
        target_user = db.query(User).filter(User.id == target_user_id).first()
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=LicenseErrorCodes.get_error_response(
                    LicenseErrorCodes.NOT_FOUND, {"resource": "user"}
                ).dict(),
            )

        # Use service to assign license
        license = LicenseService.assign_license(
            db=db,
            user_id=target_user_id,
            license_type=request_data.type,
            scope=request_data.scope,
            actor_type="admin" if is_admin and target_user_id != current_user.id else "user",
            actor_id=str(current_user.id),
            ip_address=client_ip,
            user_agent=user_agent,
        )

        db.commit()

        # Build response
        license_response = LicenseResponse(
            id=license.id,
            type=license.type,
            scope=license.scope,
            status=license.status,
            starts_at=license.starts_at,
            ends_at=license.ends_at,
        )

        response = LicenseAssignResponse(
            license=license_response,
            message="License assigned successfully",
            message_tr="Lisans başarıyla atandı",
        )

        # Store idempotent response if key provided
        if idempotency_key:
            await IdempotencyService.store_response(
                db,
                idempotency_key,
                current_user.id,
                response.dict(),
                endpoint="/api/v1/license/assign",
                method="POST",
                status_code=200,
            )

        logger.info(
            f"License assigned successfully",
            extra={
                "operation": "license_assign_success",
                "user_id": current_user.id,
                "target_user_id": target_user_id,
                "license_id": license.id,
                "license_type": request_data.type,
                "operation_id": operation_id,
            },
        )

        return response

    except LicenseStateError as e:
        if "already has an active license" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=LicenseErrorCodes.get_error_response(
                    LicenseErrorCodes.ACTIVE_LICENSE_EXISTS
                ).dict(),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=LicenseErrorCodes.get_error_response(
                LicenseErrorCodes.VALIDATION_ERROR, {"message": str(e)}
            ).dict(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to assign license",
            exc_info=True,
            extra={
                "operation": "license_assign_failed",
                "user_id": current_user.id,
                "operation_id": operation_id,
                "error_type": type(e).__name__,
            },
        )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=LicenseErrorCodes.get_error_response(LicenseErrorCodes.INTERNAL_ERROR).dict(),
        )


@router.post("/extend", response_model=LicenseExtendResponse)
async def extend_license(
    request_data: LicenseExtendRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Extend an existing license.

    **Ultra-Enterprise Features:**
    - Extend active license by specified duration
    - Admin can extend any user's license
    - Full audit trail and Turkish KVKV compliance
    - Idempotency support

    **Error Codes:**
    - 409 LIC_NOT_ACTIVE: License is not active or expired
    - 404 NOT_FOUND: License not found
    - 403 FORBIDDEN: Insufficient permissions
    """

    client_ip, user_agent = get_client_info(request)
    operation_id = str(uuid.uuid4())

    try:
        # Validate extension type
        if not LicenseTypeValidator.validate_type(request_data.type):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=LicenseErrorCodes.get_error_response(
                    LicenseErrorCodes.INVALID_TYPE,
                    {"valid_types": LicenseTypeValidator.VALID_TYPES},
                ).dict(),
            )

        # Determine target user
        target_user_id = request_data.user_id or current_user.id
        # Use rbac_business_service instead of custom role checking
        is_admin = (
            rbac_business_service.has_any_role(current_user, ["admin", "super_admin"])
            if hasattr(rbac_business_service, "has_any_role")
            else check_role(current_user, ["admin", "super_admin"])
        )

        # Authorization check
        if target_user_id != current_user.id and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=LicenseErrorCodes.get_error_response(LicenseErrorCodes.FORBIDDEN).dict(),
            )

        # Check idempotency if key provided
        if idempotency_key:
            existing_response = await IdempotencyService.get_response(
                db, idempotency_key, current_user.id, endpoint="/api/v1/license/extend"
            )
            if existing_response:
                logger.info(f"Returning idempotent response for key {idempotency_key[:20]}...")
                return existing_response

        # Find license to extend
        if request_data.license_id:
            license = (
                db.query(License)
                .filter(License.id == request_data.license_id, License.user_id == target_user_id)
                .first()
            )
        else:
            # Find user's active license
            license = LicenseService.get_active_license(db, target_user_id)

        if not license:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=LicenseErrorCodes.get_error_response(LicenseErrorCodes.NOT_FOUND).dict(),
            )

        # Store old end date for response
        previous_ends_at = license.ends_at

        # Use service to extend license
        extended_license = LicenseService.extend_license(
            db=db,
            license_id=license.id,
            extension_type=request_data.type,
            actor_type="admin" if is_admin and target_user_id != current_user.id else "user",
            actor_id=str(current_user.id),
            reason=f"License extended by {request_data.type}",
            ip_address=client_ip,
            user_agent=user_agent,
        )

        db.commit()

        # Calculate added months
        added_months = LicenseTypeValidator.get_months(request_data.type)

        response = LicenseExtendResponse(
            license_id=extended_license.id,
            previous_ends_at=previous_ends_at,
            new_ends_at=extended_license.ends_at,
            added_months=added_months,
            message="License extended successfully",
            message_tr="Lisans başarıyla uzatıldı",
        )

        # Store idempotent response if key provided
        if idempotency_key:
            await IdempotencyService.store_response(
                db,
                idempotency_key,
                current_user.id,
                response.dict(),
                endpoint="/api/v1/license/extend",
                method="POST",
                status_code=200,
            )

        logger.info(
            f"License extended successfully",
            extra={
                "operation": "license_extend_success",
                "user_id": current_user.id,
                "target_user_id": target_user_id,
                "license_id": license.id,
                "extension_type": request_data.type,
                "added_months": added_months,
                "operation_id": operation_id,
            },
        )

        return response

    except LicenseStateError as e:
        if "cannot be extended" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=LicenseErrorCodes.get_error_response(
                    LicenseErrorCodes.LIC_NOT_ACTIVE
                ).dict(),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=LicenseErrorCodes.get_error_response(
                LicenseErrorCodes.VALIDATION_ERROR, {"message": str(e)}
            ).dict(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to extend license",
            exc_info=True,
            extra={
                "operation": "license_extend_failed",
                "user_id": current_user.id,
                "operation_id": operation_id,
                "error_type": type(e).__name__,
            },
        )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=LicenseErrorCodes.get_error_response(LicenseErrorCodes.INTERNAL_ERROR).dict(),
        )


@router.post("/cancel", response_model=LicenseCancelResponse)
async def cancel_license(
    request_data: LicenseCancelRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
):
    """
    Cancel an active license.

    **Ultra-Enterprise Features:**
    - Cancel active license with reason tracking
    - Admin can cancel any user's license
    - Full audit trail and Turkish KVKV compliance
    - Idempotency support

    **Error Codes:**
    - 409 ALREADY_CANCELED: License is already canceled
    - 404 NOT_FOUND: License not found
    - 403 FORBIDDEN: Insufficient permissions
    """

    client_ip, user_agent = get_client_info(request)
    operation_id = str(uuid.uuid4())

    try:
        # Determine target user
        target_user_id = request_data.user_id or current_user.id
        # Use rbac_business_service instead of custom role checking
        is_admin = (
            rbac_business_service.has_any_role(current_user, ["admin", "super_admin"])
            if hasattr(rbac_business_service, "has_any_role")
            else check_role(current_user, ["admin", "super_admin"])
        )

        # Authorization check
        if target_user_id != current_user.id and not is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=LicenseErrorCodes.get_error_response(LicenseErrorCodes.FORBIDDEN).dict(),
            )

        # Check idempotency if key provided
        if idempotency_key:
            existing_response = await IdempotencyService.get_response(
                db, idempotency_key, current_user.id, endpoint="/api/v1/license/cancel"
            )
            if existing_response:
                logger.info(f"Returning idempotent response for key {idempotency_key[:20]}...")
                return existing_response

        # Find license to cancel
        if request_data.license_id:
            license = (
                db.query(License)
                .filter(License.id == request_data.license_id, License.user_id == target_user_id)
                .first()
            )
        else:
            # Find user's active license
            license = LicenseService.get_active_license(db, target_user_id)

        if not license:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=LicenseErrorCodes.get_error_response(LicenseErrorCodes.NOT_FOUND).dict(),
            )

        # Use service to cancel license
        canceled_license = LicenseService.cancel_license(
            db=db,
            license_id=license.id,
            reason=request_data.reason,
            actor_type="admin" if is_admin and target_user_id != current_user.id else "user",
            actor_id=str(current_user.id),
            ip_address=client_ip,
            user_agent=user_agent,
        )

        db.commit()

        response = LicenseCancelResponse(
            license_id=canceled_license.id,
            status="canceled",
            canceled_at=canceled_license.canceled_at,
            reason=request_data.reason,
            message="License canceled successfully",
            message_tr="Lisans başarıyla iptal edildi",
        )

        # Store idempotent response if key provided
        if idempotency_key:
            await IdempotencyService.store_response(
                db,
                idempotency_key,
                current_user.id,
                response.dict(),
                endpoint="/api/v1/license/cancel",
                method="POST",
                status_code=200,
            )

        logger.info(
            f"License canceled successfully",
            extra={
                "operation": "license_cancel_success",
                "user_id": current_user.id,
                "target_user_id": target_user_id,
                "license_id": license.id,
                "reason": request_data.reason,
                "operation_id": operation_id,
            },
        )

        return response

    except LicenseStateError as e:
        if "cannot be canceled" in str(e):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=LicenseErrorCodes.get_error_response(
                    LicenseErrorCodes.ALREADY_CANCELED
                ).dict(),
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=LicenseErrorCodes.get_error_response(
                LicenseErrorCodes.VALIDATION_ERROR, {"message": str(e)}
            ).dict(),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "Failed to cancel license",
            exc_info=True,
            extra={
                "operation": "license_cancel_failed",
                "user_id": current_user.id,
                "operation_id": operation_id,
                "error_type": type(e).__name__,
            },
        )
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=LicenseErrorCodes.get_error_response(LicenseErrorCodes.INTERNAL_ERROR).dict(),
        )


@router.get("/me", response_model=LicenseMeResponse)
async def get_my_license(
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """
    Get current user's license status and details.

    **Ultra-Enterprise Features:**
    - Comprehensive license status information
    - Turkish localization with warnings
    - KVKV compliant data handling
    - Real-time status calculation

    **Response includes:**
    - License status (active, expired, trial, none)
    - Remaining days and expiry date
    - License scope and features
    - Turkish warning messages
    """

    client_ip, user_agent = get_client_info(request)
    operation_id = str(uuid.uuid4())

    try:
        # Get user's active license
        license = LicenseService.get_active_license(db, current_user.id)

        if not license:
            # No active license found
            status_tr, warning_message_tr = get_status_translation("none")

            logger.info(
                "No license found for user",
                extra={
                    "operation": "license_status_check",
                    "user_id": current_user.id,
                    "status": "none",
                    "operation_id": operation_id,
                },
            )

            return LicenseMeResponse(
                status="none",
                type=None,
                ends_at=None,
                remaining_days=None,
                scope=None,
                status_tr=status_tr,
                warning_message_tr=warning_message_tr,
            )

        # Calculate license status
        now = datetime.now(timezone.utc)
        is_active = license.ends_at > now
        days_remaining = (license.ends_at - now).days if is_active else 0

        # Determine effective status
        if license.status == "canceled":
            effective_status = "canceled"
        elif not is_active:
            effective_status = "expired"
        else:
            effective_status = license.status  # active, trial, etc.

        # Get Turkish translations
        status_tr, warning_message_tr = get_status_translation(effective_status, days_remaining)

        response = LicenseMeResponse(
            status=effective_status,
            type=license.type if effective_status in ["active", "trial"] else None,
            ends_at=license.ends_at if effective_status in ["active", "trial"] else None,
            remaining_days=days_remaining if effective_status in ["active", "trial"] else None,
            scope=license.scope if effective_status in ["active", "trial"] else None,
            status_tr=status_tr,
            warning_message_tr=warning_message_tr,
        )

        logger.info(
            "License status checked successfully",
            extra={
                "operation": "license_status_check",
                "user_id": current_user.id,
                "license_id": license.id,
                "status": effective_status,
                "days_remaining": days_remaining,
                "operation_id": operation_id,
            },
        )

        return response

    except Exception as e:
        logger.error(
            "Failed to check license status",
            exc_info=True,
            extra={
                "operation": "license_status_check_failed",
                "user_id": current_user.id,
                "operation_id": operation_id,
                "error_type": type(e).__name__,
            },
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=LicenseErrorCodes.get_error_response(LicenseErrorCodes.INTERNAL_ERROR).dict(),
        )
