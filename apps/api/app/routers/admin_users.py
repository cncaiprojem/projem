"""
Admin User Management Router for Task 3.4

Ultra enterprise admin-only endpoints for user management with:
- GET /admin/users - List all users (admin only)
- GET /admin/users/{user_id} - Get specific user details
- PUT /admin/users/{user_id}/role - Update user role
- GET /admin/security-events - Security event monitoring
- GET /admin/permissions - System permission overview
- Banking-level security with comprehensive audit logging
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import desc, func
from sqlalchemy.orm import Session as DBSession

from ..core.logging import get_logger
from ..db import get_db
from ..dependencies.auth_dependencies import require_admin, require_scopes
from ..middleware.jwt_middleware import AuthenticatedUser
from ..models.enums import UserRole
from ..models.user import User
from ..schemas.auth import UserOut
from ..schemas.rbac_schemas import (
    PermissionCheckRequest,
    PermissionCheckResponse,
    RoleUpdateRequest,
    RoleUpdateResponse,
    SecurityEventResponse,
    SystemPermissionsResponse,
    UserPermissionSummary,
)
from ..services.rbac_service import rbac_business_service

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/admin",
    tags=["Admin - Kullanıcı Yönetimi"],
    dependencies=[Depends(require_scopes("admin:users"))],  # All endpoints require admin:users scope
    responses={
        401: {"description": "Kimlik doğrulama gerekli"},
        403: {"description": "Admin yetkisi gerekli"},
        404: {"description": "Kaynak bulunamadı"},
        500: {"description": "Sunucu hatası"},
    }
)


@router.get("/users", response_model=list[UserOut])
def list_users(
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_scopes("admin:users")),
    skip: int = Query(0, ge=0, description="Atlanacak kayıt sayısı"),
    limit: int = Query(100, ge=1, le=1000, description="Maksimum kayıt sayısı"),
    role: UserRole | None = Query(None, description="Role göre filtrele"),
    is_active: bool | None = Query(None, description="Aktiflik durumuna göre filtrele"),
    search: str | None = Query(None, min_length=2, max_length=100, description="Email veya isim araması")
):
    """
    List all users in the system (admin only).
    
    Requires admin:users scope.
    """
    start_time = datetime.now(UTC)

    # Build query
    query = db.query(User)

    # Apply filters
    if role:
        query = query.filter(User.role == role)

    if is_active is not None:
        query = query.filter(User.is_active == is_active)

    if search:
        search_pattern = f"%{search.lower()}%"
        query = query.filter(
            func.lower(User.email).like(search_pattern) |
            func.lower(User.full_name).like(search_pattern)
        )

    # Order by creation date (newest first)
    query = query.order_by(desc(User.created_at))

    # Apply pagination
    users = query.offset(skip).limit(limit).all()

    elapsed_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

    # Log admin action
    logger.info("Admin listed users", extra={
        'operation': 'admin_list_users',
        'admin_user_id': current_user.user_id,
        'filters': {
            'role': role.value if role else None,
            'is_active': is_active,
            'search': search
        },
        'result_count': len(users),
        'skip': skip,
        'limit': limit,
        'elapsed_ms': elapsed_ms,
        'client_ip': request.client.host if request.client else None
    })

    return users


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_admin())
):
    """
    Get specific user details (admin only).
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kullanıcı bulunamadı"
        )

    # Log admin action
    logger.info("Admin viewed user details", extra={
        'operation': 'admin_get_user',
        'admin_user_id': current_user.user_id,
        'target_user_id': user_id,
        'client_ip': request.client.host if request.client else None
    })

    return user


@router.get("/users/{user_id}/permissions", response_model=UserPermissionSummary)
def get_user_permissions(
    user_id: int,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_admin())
):
    """
    Get user permission summary (admin only).
    """
    permissions = rbac_business_service.get_user_permissions(db, user_id)
    if not permissions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kullanıcı bulunamadı"
        )

    # Log admin action
    logger.info("Admin viewed user permissions", extra={
        'operation': 'admin_get_user_permissions',
        'admin_user_id': current_user.user_id,
        'target_user_id': user_id,
        'client_ip': request.client.host if request.client else None
    })

    return permissions


@router.put("/users/{user_id}/role", response_model=RoleUpdateResponse)
def update_user_role(
    user_id: int,
    role_update: RoleUpdateRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_admin())
):
    """
    Update user role (admin only).
    
    Requires admin:users scope.
    """
    # Validate request
    if role_update.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL'deki user_id ile request body'deki user_id eşleşmiyor"
        )

    # Check if target user exists
    target_user = db.query(User).filter(User.id == user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kullanıcı bulunamadı"
        )

    # Prevent admin from changing their own role (safety measure)
    if user_id == current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kendi rolünüzü değiştiremezsiniz"
        )

    # Update role
    result = rbac_business_service.update_user_role(
        db=db,
        user_id=user_id,
        new_role=role_update.new_role,
        updated_by_user_id=current_user.user_id,
        reason=role_update.reason
    )

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Kullanıcı bulunamadı"
        )

    # Log admin action
    logger.warning("Admin updated user role", extra={
        'operation': 'admin_update_user_role',
        'admin_user_id': current_user.user_id,
        'target_user_id': user_id,
        'old_role': result.old_role.value,
        'new_role': result.new_role.value,
        'reason': role_update.reason,
        'client_ip': request.client.host if request.client else None
    })

    return result


@router.get("/security-events", response_model=list[SecurityEventResponse])
def list_security_events(
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_scopes("admin:system")),
    user_id: int | None = Query(None, description="Kullanıcı ID'ye göre filtrele"),
    event_type: str | None = Query(None, description="Event tipine göre filtrele"),
    hours: int = Query(24, ge=1, le=168, description="Kaç saat geriye bakılacak"),
    skip: int = Query(0, ge=0, description="Atlanacak kayıt sayısı"),
    limit: int = Query(100, ge=1, le=1000, description="Maksimum kayıt sayısı")
):
    """
    List security events for monitoring (admin only).
    
    Requires admin:system scope.
    """
    start_date = datetime.now(UTC) - timedelta(hours=hours)

    event_types = [event_type] if event_type else None

    events = rbac_business_service.get_security_events(
        db=db,
        user_id=user_id,
        event_types=event_types,
        start_date=start_date,
        limit=limit,
        offset=skip
    )

    # Log admin action
    logger.info("Admin viewed security events", extra={
        'operation': 'admin_list_security_events',
        'admin_user_id': current_user.user_id,
        'filters': {
            'user_id': user_id,
            'event_type': event_type,
            'hours': hours
        },
        'result_count': len(events),
        'client_ip': request.client.host if request.client else None
    })

    return events


@router.get("/security-events/summary")
def get_security_events_summary(
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_scopes("admin:system")),
    hours: int = Query(24, ge=1, le=168, description="Kaç saat geriye bakılacak")
):
    """
    Get security events summary for dashboard (admin only).
    
    Requires admin:system scope.
    """
    summary = rbac_business_service.get_recent_security_events_summary(db, hours)

    # Log admin action
    logger.info("Admin viewed security events summary", extra={
        'operation': 'admin_security_events_summary',
        'admin_user_id': current_user.user_id,
        'hours': hours,
        'total_events': summary.get('total_events', 0),
        'client_ip': request.client.host if request.client else None
    })

    return summary


@router.get("/permissions", response_model=SystemPermissionsResponse)
def get_system_permissions(
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_scopes("admin:system"))
):
    """
    Get comprehensive system permission information (admin only).
    
    Requires admin:system scope.
    """
    permissions = rbac_business_service.get_system_permissions(db)

    # Log admin action
    logger.info("Admin viewed system permissions", extra={
        'operation': 'admin_get_system_permissions',
        'admin_user_id': current_user.user_id,
        'total_roles': len(permissions.available_roles),
        'total_scopes': len(permissions.available_scopes),
        'client_ip': request.client.host if request.client else None
    })

    return permissions


@router.post("/check-permission", response_model=PermissionCheckResponse)
def check_user_permission(
    permission_check: PermissionCheckRequest,
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_admin())
):
    """
    Check if specific user has permission for resource/action (admin only).
    
    Useful for debugging permission issues.
    """
    result = rbac_business_service.check_user_permission(
        db=db,
        user_id=permission_check.user_id,
        resource=permission_check.resource,
        action=permission_check.action,
        context=permission_check.context
    )

    # Log admin action
    logger.info("Admin checked user permission", extra={
        'operation': 'admin_check_permission',
        'admin_user_id': current_user.user_id,
        'target_user_id': permission_check.user_id,
        'resource': permission_check.resource,
        'action': permission_check.action,
        'permission_allowed': result.allowed,
        'client_ip': request.client.host if request.client else None
    })

    return result


@router.get("/users/stats")
def get_user_statistics(
    request: Request,
    db: DBSession = Depends(get_db),
    current_user: AuthenticatedUser = Depends(require_scopes("admin:system"))
):
    """
    Get user statistics by role and status (admin only).
    
    Requires admin:system scope.
    """
    stats = rbac_business_service.get_role_statistics(db)

    # Additional statistics
    total_users = db.query(func.count(User.id)).scalar()
    active_users = db.query(func.count(User.id)).filter(User.is_active == True).scalar()
    locked_users = db.query(func.count(User.id)).filter(User.account_locked_until > datetime.now(UTC)).scalar()

    # Recent login statistics
    recent_logins = (
        db.query(func.count(User.id))
        .filter(User.last_successful_login_at >= datetime.now(UTC) - timedelta(days=30))
        .scalar()
    )

    result = {
        'users_by_role': stats,
        'total_users': total_users,
        'active_users': active_users,
        'locked_users': locked_users,
        'recent_logins_30d': recent_logins,
        'generated_at': datetime.now(UTC).isoformat()
    }

    # Log admin action
    logger.info("Admin viewed user statistics", extra={
        'operation': 'admin_user_statistics',
        'admin_user_id': current_user.user_id,
        'total_users': total_users,
        'active_users': active_users,
        'client_ip': request.client.host if request.client else None
    })

    return result
