"""
User Profile Router for Task 3.4

User profile management endpoints with mixed RBAC permissions:
- GET /me - Get current user profile (authenticated users)
- PUT /me - Update current user profile (profile:write scope)
- GET /me/permissions - Get current user permissions
- DELETE /me/account - Deactivate account (self-service)
- Banking-level security with audit logging
"""

from typing import Optional, Dict, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session as DBSession
from pydantic import BaseModel, Field

from ..models.user import User
from ..models.audit_log import AuditLog
from ..models.enums import AuditAction, UserRole
from ..schemas.auth import UserProfileResponse
from ..schemas.rbac_schemas import UserPermissionSummary
from ..dependencies.auth_dependencies import require_auth, require_scopes
from ..middleware.jwt_middleware import AuthenticatedUser
from ..services.rbac_service import rbac_business_service
from ..core.logging import get_logger
from ..db import get_db

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/me",
    tags=["Kullanıcı Profili"],
    responses={
        401: {"description": "Kimlik doğrulama gerekli"},
        403: {"description": "Yetersiz yetki"},
        404: {"description": "Kaynak bulunamadı"},
        500: {"description": "Sunucu hatası"},
    }
)


class UserProfileUpdate(BaseModel):
    """Schema for user profile updates."""
    
    full_name: Optional[str] = Field(None, min_length=2, max_length=255)
    display_name: Optional[str] = Field(None, min_length=2, max_length=100)
    company_name: Optional[str] = Field(None, max_length=255)
    address: Optional[str] = Field(None, max_length=1000)
    
    class Config:
        json_schema_extra = {
            "example": {
                "full_name": "Ahmet Yılmaz",
                "display_name": "Ahmet",
                "company_name": "ABC Makina Ltd.",
                "address": "Ankara, Türkiye"
            }
        }


class AccountDeactivationRequest(BaseModel):
    """Schema for account deactivation request."""
    
    reason: str = Field(..., min_length=10, max_length=500)
    confirm_deactivation: bool = Field(..., description="Must be true to confirm")
    
    class Config:
        json_schema_extra = {
            "example": {
                "reason": "Artık sistemi kullanmıyorum",
                "confirm_deactivation": True
            }
        }


@router.get("", response_model=UserProfileResponse)
def get_current_user_profile(
    request: Request,
    current_user: AuthenticatedUser = Depends(require_auth()),
    db: DBSession = Depends(get_db)
):
    """
    Get current user profile information.
    
    Requires: Basic authentication (any authenticated user)
    """
    # Log profile access
    logger.info("User accessed own profile", extra={
        'operation': 'get_user_profile',
        'user_id': current_user.user_id,
        'role': current_user.role.value,
        'client_ip': request.client.host if request.client else None
    })
    
    # Return current user information
    return current_user.user


@router.put("", response_model=UserProfileResponse)
def update_current_user_profile(
    profile_update: UserProfileUpdate,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_scopes("profile:write")),
    db: DBSession = Depends(get_db)
):
    """
    Update current user profile information.
    
    Requires: profile:write scope
    """
    user = current_user.user
    
    # Track changes for audit log
    changes = {}
    
    # Update fields that were provided
    if profile_update.full_name is not None:
        old_value = user.full_name
        user.full_name = profile_update.full_name
        changes['full_name'] = {'old': old_value, 'new': profile_update.full_name}
    
    if profile_update.display_name is not None:
        old_value = user.display_name
        user.display_name = profile_update.display_name
        changes['display_name'] = {'old': old_value, 'new': profile_update.display_name}
    
    if profile_update.company_name is not None:
        old_value = user.company_name
        user.company_name = profile_update.company_name
        changes['company_name'] = {'old': old_value, 'new': profile_update.company_name}
    
    if profile_update.address is not None:
        old_value = user.address
        user.address = profile_update.address
        changes['address'] = {'old': old_value, 'new': profile_update.address}
    
    # Update timestamp
    user.updated_at = datetime.now(timezone.utc)
    
    # Create audit log entry
    if changes:
        audit_log = AuditLog(
            action=AuditAction.UPDATE,
            resource_type="User",
            resource_id=str(user.id),
            actor_user_id=current_user.user_id,
            changes=changes,
            reason="Profile update by user",
            created_at=datetime.now(timezone.utc)
        )
        db.add(audit_log)
    
    # Save changes
    db.commit()
    db.refresh(user)
    
    # Log profile update
    logger.info("User updated own profile", extra={
        'operation': 'update_user_profile',
        'user_id': current_user.user_id,
        'changes': list(changes.keys()),
        'client_ip': request.client.host if request.client else None
    })
    
    return user


@router.get("/permissions", response_model=UserPermissionSummary)
def get_current_user_permissions(
    request: Request,
    current_user: AuthenticatedUser = Depends(require_auth()),
    db: DBSession = Depends(get_db)
):
    """
    Get current user permission summary.
    
    Requires: Basic authentication (any authenticated user)
    """
    # Get permissions from RBAC service
    permissions = rbac_business_service.get_user_permissions(db, current_user.user_id)
    
    # Log permission access
    logger.info("User accessed own permissions", extra={
        'operation': 'get_user_permissions',
        'user_id': current_user.user_id,
        'role': current_user.role.value,
        'scope_count': len(permissions.scopes) if permissions else 0,
        'client_ip': request.client.host if request.client else None
    })
    
    return permissions


@router.get("/sessions")
def get_current_user_sessions(
    request: Request,
    current_user: AuthenticatedUser = Depends(require_auth()),
    db: DBSession = Depends(get_db)
):
    """
    Get current user's active sessions.
    
    Requires: Basic authentication (any authenticated user)
    """
    from ..models.session import Session
    
    # Get user's active sessions
    sessions = (
        db.query(Session)
        .filter(Session.user_id == current_user.user_id)
        .filter(Session.expires_at > datetime.now(timezone.utc))
        .order_by(Session.last_activity_at.desc())
        .all()
    )
    
    session_list = []
    for session in sessions:
        is_current = session.id == current_user.session_id
        
        session_list.append({
            'session_id': str(session.id),
            'is_current': is_current,
            'created_at': session.created_at.isoformat(),
            'last_activity_at': session.last_activity_at.isoformat() if session.last_activity_at else None,
            'expires_at': session.expires_at.isoformat(),
            'device_fingerprint': session.device_fingerprint,
            'ip_address': session.ip_address,
            'user_agent': session.user_agent[:100] + '...' if session.user_agent and len(session.user_agent) > 100 else session.user_agent
        })
    
    # Log session access
    logger.info("User accessed own sessions", extra={
        'operation': 'get_user_sessions',
        'user_id': current_user.user_id,
        'active_sessions': len(session_list),
        'client_ip': request.client.host if request.client else None
    })
    
    return {
        'user_id': current_user.user_id,
        'active_sessions': session_list,
        'total_sessions': len(session_list)
    }


@router.delete("/sessions/{session_id}")
def revoke_user_session(
    session_id: str,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_auth()),
    db: DBSession = Depends(get_db)
):
    """
    Revoke a specific user session.
    
    Requires: Basic authentication (users can only revoke their own sessions)
    """
    from ..models.session import Session
    
    # Get the session
    session = (
        db.query(Session)
        .filter(Session.id == session_id)
        .filter(Session.user_id == current_user.user_id)  # Users can only revoke their own sessions
        .first()
    )
    
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Oturum bulunamadı veya size ait değil"
        )
    
    # Prevent user from revoking their current session
    if session.id == current_user.session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mevcut oturumunuzu sonlandıramazsınız"
        )
    
    # Revoke session by setting expiry to past
    session.expires_at = datetime.now(timezone.utc)
    session.revoked_at = datetime.now(timezone.utc)
    session.revocation_reason = "User requested session termination"
    
    db.commit()
    
    # Log session revocation
    logger.warning("User revoked own session", extra={
        'operation': 'revoke_user_session',
        'user_id': current_user.user_id,
        'revoked_session_id': session_id,
        'client_ip': request.client.host if request.client else None
    })
    
    return {
        'message': 'Oturum başarıyla sonlandırıldı',
        'session_id': session_id
    }


@router.delete("/account")
def deactivate_account(
    deactivation: AccountDeactivationRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(require_auth()),
    db: DBSession = Depends(get_db)
):
    """
    Deactivate current user account (self-service).
    
    Requires: Basic authentication (users can deactivate their own account)
    """
    # Validate confirmation
    if not deactivation.confirm_deactivation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hesap deaktivasyonu onaylanmalıdır"
        )
    
    user = current_user.user
    
    # Prevent admin users from self-deactivating (safety measure)
    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin kullanıcılar kendi hesaplarını deaktive edemez"
        )
    
    # Deactivate account
    user.is_active = False
    user.account_status = 'deactivated'
    user.deactivated_at = datetime.now(timezone.utc)
    user.deactivation_reason = deactivation.reason
    user.updated_at = datetime.now(timezone.utc)
    
    # Create audit log entry
    audit_log = AuditLog(
        action=AuditAction.USER_DELETE,  # Closest to deactivation
        resource_type="User",
        resource_id=str(user.id),
        actor_user_id=current_user.user_id,
        changes={
            'account_status': {'old': 'active', 'new': 'deactivated'},
            'is_active': {'old': True, 'new': False}
        },
        reason=f"Self-deactivation: {deactivation.reason}",
        created_at=datetime.now(timezone.utc)
    )
    db.add(audit_log)
    
    # Revoke all user sessions
    from ..models.session import Session
    user_sessions = (
        db.query(Session)
        .filter(Session.user_id == user.id)
        .filter(Session.expires_at > datetime.now(timezone.utc))
        .all()
    )
    
    for session in user_sessions:
        session.expires_at = datetime.now(timezone.utc)
        session.revoked_at = datetime.now(timezone.utc)
        session.revocation_reason = "Account deactivated by user"
    
    db.commit()
    
    # Log account deactivation
    logger.warning("User deactivated own account", extra={
        'operation': 'deactivate_account',
        'user_id': current_user.user_id,
        'reason': deactivation.reason,
        'revoked_sessions': len(user_sessions),
        'client_ip': request.client.host if request.client else None
    })
    
    return {
        'message': 'Hesabınız başarıyla deaktive edildi',
        'deactivated_at': user.deactivated_at.isoformat(),
        'revoked_sessions': len(user_sessions)
    }