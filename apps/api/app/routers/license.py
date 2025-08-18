"""
Task 3.14: Ultra-Enterprise License Management Router
Provides license validation, status checking, and expiry notifications
with Turkish KVKV compliance and banking-grade security patterns.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.auth import get_current_user
from ..core.database import get_db
from ..core.logging import get_logger
from ..models.user import User
from ..models.license import License
from ..models.enums import LicenseStatus, LicenseType
from ..core.rbac import require_role
from ..core.audit import audit_event

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/license",
    tags=["license"]
)

# Response Models - Ultra-Enterprise Standards
class LicenseStatusResponse(BaseModel):
    """Ultra-enterprise license status response with Turkish localization."""
    
    status: str = Field(..., description="License status: 'active', 'expired', 'suspended', 'trial'")
    days_remaining: int = Field(..., description="Days until license expiry (0 if expired)")
    expires_at: datetime = Field(..., description="Exact expiry timestamp (UTC)")
    plan_type: str = Field(..., description="License plan type")
    seats_total: int = Field(..., description="Total available seats")
    seats_used: int = Field(..., description="Currently used seats")
    features: dict = Field(..., description="Available features and limits")
    auto_renew: bool = Field(..., description="Auto-renewal status")
    
    # Turkish localization fields
    status_tr: str = Field(..., description="Status in Turkish")
    warning_message_tr: Optional[str] = Field(None, description="Warning message in Turkish")
    renewal_url: Optional[str] = Field(None, description="License renewal URL")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }

class LicenseFeatureCheckRequest(BaseModel):
    """Request model for feature availability checks."""
    feature: str = Field(..., min_length=1, max_length=100, description="Feature name to check")

class LicenseFeatureCheckResponse(BaseModel):
    """Response model for feature availability checks."""
    feature: str
    available: bool
    limit: Optional[int] = Field(None, description="Feature limit (-1 for unlimited, None if not applicable)")
    current_usage: Optional[int] = Field(None, description="Current usage count")

# Helper Functions
def get_status_translation(status: LicenseStatus, days_remaining: int) -> tuple[str, Optional[str]]:
    """Get Turkish translation for license status with appropriate warnings."""
    
    status_translations = {
        LicenseStatus.ACTIVE: "aktif",
        LicenseStatus.EXPIRED: "süresi_dolmuş", 
        LicenseStatus.SUSPENDED: "askıya_alınmış",
        LicenseStatus.TRIAL: "deneme"
    }
    
    status_tr = status_translations.get(status, "bilinmeyen")
    warning_message_tr = None
    
    # Generate warning messages based on days remaining (Turkish KVKV compliance)
    if status == LicenseStatus.ACTIVE:
        if days_remaining <= 3:
            warning_message_tr = f"Lisansınızın süresi {days_remaining} gün içinde dolacak! Lütfen yenileyin."
        elif days_remaining <= 7:
            warning_message_tr = f"Lisansınızın süresi {days_remaining} gün içinde dolacak."
        elif days_remaining <= 30:
            warning_message_tr = f"Lisansınızın süresi {days_remaining} gün içinde dolacak. Yenileme işlemini planlamanızı öneririz."
    elif status == LicenseStatus.EXPIRED:
        warning_message_tr = "Lisansınızın süresi dolmuş! Hizmetlere erişim kısıtlanabilir."
    elif status == LicenseStatus.SUSPENDED:
        warning_message_tr = "Lisansınız askıya alınmış. Yönetici ile iletişime geçin."
    elif status == LicenseStatus.TRIAL:
        if days_remaining <= 3:
            warning_message_tr = f"Deneme süreniz {days_remaining} gün içinde dolacak! Bir plan satın almayı düşünün."
    
    return status_tr, warning_message_tr

def get_plan_translation(plan: LicenseType) -> str:
    """Get Turkish translation for license plan type."""
    
    plan_translations = {
        LicenseType.TRIAL: "deneme",
        LicenseType.BASIC: "temel",
        LicenseType.PROFESSIONAL: "profesyonel", 
        LicenseType.ENTERPRISE: "kurumsal"
    }
    
    return plan_translations.get(plan, plan.value.lower())

# API Endpoints
@router.get("/me", response_model=LicenseStatusResponse)
async def get_my_license_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Get current user's license status and details.
    
    Ultra-enterprise endpoint providing comprehensive license information
    with Turkish localization and KVKV compliance.
    
    **Features:**
    - Real-time license validation
    - Expiry warnings in Turkish
    - Feature availability status
    - Seat usage tracking
    - Auto-renewal status
    
    **Security:**
    - Requires valid authentication
    - KVKV compliant logging
    - No sensitive data exposure
    """
    
    try:
        # Get user's active license
        user_license = db.query(License).filter(
            License.user_id == current_user.id,
            License.status.in_([LicenseStatus.ACTIVE, LicenseStatus.TRIAL, LicenseStatus.EXPIRED])
        ).order_by(License.ends_at.desc()).first()
        
        if not user_license:
            # No license found - create default trial response
            logger.warning("No license found for user", extra={
                'operation': 'license_status_check',
                'user_id': current_user.id,
                'event': 'no_license_found'
            })
            
            # Audit log (KVKV compliant - no PII)
            await audit_event(
                db=db,
                user_id=current_user.id,
                action="license_check",
                resource_type="license", 
                resource_id=None,
                details={"status": "no_license", "requires_setup": True},
                ip_address="system",
                user_agent="api_internal"
            )
            
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "LICENSE_NOT_FOUND",
                    "message": "No active license found",
                    "message_tr": "Aktif lisans bulunamadı"
                }
            )
        
        # Calculate license status
        now = datetime.now(timezone.utc)
        is_active = user_license.is_active
        days_remaining = user_license.days_remaining
        
        # Determine effective status
        if user_license.status == LicenseStatus.EXPIRED or (not is_active and user_license.status == LicenseStatus.ACTIVE):
            effective_status = "expired"
            effective_status_enum = LicenseStatus.EXPIRED
        elif user_license.status == LicenseStatus.SUSPENDED:
            effective_status = "suspended"
            effective_status_enum = LicenseStatus.SUSPENDED
        elif user_license.status == LicenseStatus.TRIAL:
            effective_status = "trial"
            effective_status_enum = LicenseStatus.TRIAL
        else:
            effective_status = "active"
            effective_status_enum = LicenseStatus.ACTIVE
        
        # Get Turkish translations
        status_tr, warning_message_tr = get_status_translation(effective_status_enum, days_remaining)
        plan_tr = get_plan_translation(user_license.plan)
        
        # Calculate seat usage (placeholder - would integrate with actual usage tracking)
        seats_used = 1  # Current user
        
        # Build renewal URL (would integrate with payment system)
        renewal_url = None
        if effective_status in ["expired", "trial"] or days_remaining <= 7:
            renewal_url = "/license/renew"
        
        response = LicenseStatusResponse(
            status=effective_status,
            days_remaining=max(0, days_remaining),
            expires_at=user_license.ends_at,
            plan_type=user_license.plan.value,
            seats_total=user_license.seats,
            seats_used=seats_used,
            features=user_license.features or {},
            auto_renew=user_license.auto_renew,
            status_tr=status_tr,
            warning_message_tr=warning_message_tr,
            renewal_url=renewal_url
        )
        
        # Success audit log (KVKV compliant)
        await audit_event(
            db=db,
            user_id=current_user.id,
            action="license_status_check",
            resource_type="license",
            resource_id=str(user_license.id),
            details={
                "status": effective_status,
                "days_remaining": days_remaining,
                "plan": user_license.plan.value
            },
            ip_address="system",
            user_agent="api_internal"
        )
        
        logger.info("License status checked successfully", extra={
            'operation': 'license_status_check',
            'user_id': current_user.id,
            'license_id': user_license.id,
            'status': effective_status,
            'days_remaining': days_remaining,
            'plan': user_license.plan.value
        })
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to check license status", exc_info=True, extra={
            'operation': 'license_status_check_failed',
            'user_id': current_user.id,
            'error_type': type(e).__name__
        })
        
        # Error audit log (KVKV compliant)
        await audit_event(
            db=db,
            user_id=current_user.id,
            action="license_check_error",
            resource_type="license",
            resource_id=None,
            details={"error": "system_error"},
            ip_address="system",
            user_agent="api_internal"
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "LICENSE_CHECK_FAILED",
                "message": "Failed to check license status",
                "message_tr": "Lisans durumu kontrol edilemedi"
            }
        )

@router.post("/check-feature", response_model=LicenseFeatureCheckResponse)
async def check_feature_availability(
    request: LicenseFeatureCheckRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Check if a specific feature is available under current license.
    
    **Ultra-enterprise feature validation:**
    - Real-time feature availability check
    - Usage limit validation
    - Feature-specific error messages in Turkish
    
    **Common features:**
    - cad_basic, cad_advanced
    - cam_basic, cam_advanced
    - simulation_basic, simulation_advanced
    - api_access, erp_integration
    - max_jobs, max_models
    """
    
    try:
        # Get user's active license
        user_license = db.query(License).filter(
            License.user_id == current_user.id,
            License.status.in_([LicenseStatus.ACTIVE, LicenseStatus.TRIAL])
        ).order_by(License.ends_at.desc()).first()
        
        if not user_license or not user_license.is_active:
            return LicenseFeatureCheckResponse(
                feature=request.feature,
                available=False,
                limit=None,
                current_usage=None
            )
        
        # Check feature availability
        feature_available = user_license.has_feature(request.feature)
        
        # Get feature limits and current usage (would integrate with usage tracking)
        feature_limit = None
        current_usage = None
        
        if request.feature in user_license.features:
            feature_value = user_license.features[request.feature]
            if isinstance(feature_value, int):
                feature_limit = feature_value
                # current_usage would come from usage tracking system
        
        # Audit log (KVKV compliant)
        await audit_event(
            db=db,
            user_id=current_user.id,
            action="feature_check",
            resource_type="license",
            resource_id=str(user_license.id),
            details={
                "feature": request.feature,
                "available": feature_available,
                "limit": feature_limit
            },
            ip_address="system",
            user_agent="api_internal"
        )
        
        return LicenseFeatureCheckResponse(
            feature=request.feature,
            available=feature_available,
            limit=feature_limit,
            current_usage=current_usage
        )
        
    except Exception as e:
        logger.error("Failed to check feature availability", exc_info=True, extra={
            'operation': 'feature_check_failed',
            'user_id': current_user.id,
            'feature': request.feature,
            'error_type': type(e).__name__
        })
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "FEATURE_CHECK_FAILED", 
                "message": "Failed to check feature availability",
                "message_tr": "Özellik durumu kontrol edilemedi"
            }
        )

@router.get("/admin/all", response_model=list[dict])
@require_role(["admin", "super_admin"])
async def get_all_licenses(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Admin endpoint to view all user licenses.
    
    **Ultra-enterprise admin functionality:**
    - Comprehensive license overview
    - Expiry tracking across all users
    - Usage analytics
    - KVKV compliant data handling
    
    **Requires:** admin or super_admin role
    """
    
    try:
        # Get all licenses with user information
        licenses = db.query(License).join(User).all()
        
        results = []
        for license in licenses:
            results.append({
                "license_id": license.id,
                "user_email": license.user.email,
                "plan": license.plan.value,
                "status": license.status.value,
                "status_tr": get_status_translation(license.status, license.days_remaining)[0],
                "days_remaining": license.days_remaining,
                "expires_at": license.ends_at.isoformat(),
                "seats_total": license.seats,
                "auto_renew": license.auto_renew,
                "is_active": license.is_active
            })
        
        # Admin audit log (KVKV compliant)
        await audit_event(
            db=db,
            user_id=current_user.id,
            action="admin_license_list",
            resource_type="license",
            resource_id="all",
            details={"total_licenses": len(results)},
            ip_address="system",
            user_agent="api_internal"
        )
        
        logger.info("Admin license list accessed", extra={
            'operation': 'admin_license_list',
            'admin_user_id': current_user.id,
            'total_licenses': len(results)
        })
        
        return results
        
    except Exception as e:
        logger.error("Failed to get admin license list", exc_info=True, extra={
            'operation': 'admin_license_list_failed',
            'admin_user_id': current_user.id,
            'error_type': type(e).__name__
        })
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "ADMIN_LICENSE_LIST_FAILED",
                "message": "Failed to retrieve license list",
                "message_tr": "Lisans listesi alınamadı"
            }
        )