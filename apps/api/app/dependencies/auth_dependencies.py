"""
Ultra Enterprise Authentication Dependencies for Task 3.4

FastAPI dependency injectors for RBAC enforcement with:
- require_auth() - Basic authentication check
- require_role() - Role-based access control
- require_scopes() - Scope-based permission validation
- require_admin() - Admin-only access shortcut
- Performance optimized authorization checks (<10ms)
- Comprehensive security audit logging
- Turkish localized error messages
"""

from typing import List, Callable, Optional, Union
from datetime import datetime, timezone

from fastapi import Depends, Request, HTTPException, status
from sqlalchemy.orm import Session as DBSession

from ..middleware.jwt_middleware import (
    AuthenticatedUser,
    get_current_user,
    get_current_user_optional,
    JWTAuthenticationError,
)
from ..middleware.rbac_middleware import (
    rbac_service,
    RBACError,
    RBACErrorCode,
    create_security_event_in_db,
    extract_request_metadata,
)
from ..models.enums import UserRole
from ..core.logging import get_logger
from ..db import get_db

logger = get_logger(__name__)


def _log_rbac_security_event(
    db: DBSession, request: Request, current_user: AuthenticatedUser, event_type: str
) -> None:
    """
    Shared helper function to log RBAC security events.

    Args:
        db: Database session for event logging
        request: FastAPI request object for metadata extraction
        current_user: Current authenticated user
        event_type: Type of security event to log
    """
    request_meta = extract_request_metadata(request)
    create_security_event_in_db(
        db=db,
        event_type=event_type,
        user_id=current_user.user_id,
        ip=request_meta.get("client_ip"),
        user_agent=request_meta.get("user_agent"),
    )


def require_auth() -> Callable:
    """
    Dependency to require basic authentication.

    Returns:
        AuthenticatedUser: Current authenticated user

    Raises:
        JWTAuthenticationError: If authentication fails
        RBACError: If user account is inactive
    """

    async def auth_dependency(
        request: Request,
        current_user: AuthenticatedUser = Depends(get_current_user),
        db: DBSession = Depends(get_db),
    ) -> AuthenticatedUser:
        start_time = datetime.now(timezone.utc)

        try:
            # Check user account status
            rbac_service.check_user_active(current_user.user, request)

            # Log successful authentication check
            elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            logger.debug(
                "Authentication check successful",
                extra={
                    "operation": "require_auth",
                    "user_id": current_user.user_id,
                    "role": current_user.role.value,
                    "elapsed_ms": elapsed_ms,
                    "endpoint": f"{request.method} {request.url.path}",
                },
            )

            return current_user

        except RBACError:
            # Log security event for account status issues
            _log_rbac_security_event(db, request, current_user, "account_inactive")
            raise

        except Exception as e:
            logger.error(
                "Authentication check failed",
                exc_info=True,
                extra={
                    "operation": "require_auth",
                    "user_id": getattr(current_user, "user_id", None),
                    "error_type": type(e).__name__,
                    "endpoint": f"{request.method} {request.url.path}",
                },
            )
            raise

    return auth_dependency


def require_role(required_role: Union[UserRole, str]) -> Callable:
    """
    Dependency to require minimum user role.

    Args:
        required_role: Minimum required role (UserRole enum or string)

    Returns:
        AuthenticatedUser: Current authenticated user with sufficient role

    Raises:
        RBACError: If user role is insufficient
    """
    # Convert string to UserRole enum if needed
    if isinstance(required_role, str):
        try:
            required_role = UserRole(required_role.lower())
        except ValueError:
            raise ValueError(f"Invalid role: {required_role}")

    async def role_dependency(
        request: Request,
        current_user: AuthenticatedUser = Depends(require_auth()),
        db: DBSession = Depends(get_db),
    ) -> AuthenticatedUser:
        start_time = datetime.now(timezone.utc)

        try:
            # Check role permission
            rbac_service.check_role_permission(
                user_role=current_user.role,
                required_role=required_role,
                user_id=current_user.user_id,
                request=request,
            )

            elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            logger.debug(
                "Role check successful",
                extra={
                    "operation": "require_role",
                    "user_id": current_user.user_id,
                    "user_role": current_user.role.value,
                    "required_role": required_role.value,
                    "elapsed_ms": elapsed_ms,
                    "endpoint": f"{request.method} {request.url.path}",
                },
            )

            return current_user

        except RBACError as e:
            # Log security event for role access denial
            _log_rbac_security_event(db, request, current_user, "role_required")
            raise

    return role_dependency


def require_scopes(*required_scopes: str, require_all: bool = True) -> Callable:
    """
    Dependency to require specific permission scopes.

    Args:
        required_scopes: Required permission scopes
        require_all: If True, requires all scopes; if False, requires any scope

    Returns:
        AuthenticatedUser: Current authenticated user with sufficient scopes

    Raises:
        RBACError: If user lacks required scopes
    """

    def scope_dependency(
        request: Request,
        current_user: AuthenticatedUser = Depends(require_auth()),
        db: DBSession = Depends(get_db),
    ) -> AuthenticatedUser:
        start_time = datetime.now(timezone.utc)

        try:
            # Check scope permissions
            rbac_service.check_scope_permission(
                user_role=current_user.role,
                required_scopes=list(required_scopes),
                user_id=current_user.user_id,
                request=request,
                require_all=require_all,
            )

            elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            logger.debug(
                "Scope check successful",
                extra={
                    "operation": "require_scopes",
                    "user_id": current_user.user_id,
                    "user_role": current_user.role.value,
                    "required_scopes": list(required_scopes),
                    "require_all": require_all,
                    "elapsed_ms": elapsed_ms,
                    "endpoint": f"{request.method} {request.url.path}",
                },
            )

            return current_user

        except RBACError as e:
            # Log security event for scope access denial
            _log_rbac_security_event(db, request, current_user, "insufficient_scopes")
            raise

    return scope_dependency


def require_admin() -> Callable:
    """
    Dependency to require admin role (shortcut for require_role(UserRole.ADMIN)).

    Returns:
        AuthenticatedUser: Current authenticated admin user

    Raises:
        RBACError: If user is not admin
    """

    async def admin_dependency(
        request: Request,
        current_user: AuthenticatedUser = Depends(require_auth()),
        db: DBSession = Depends(get_db),
    ) -> AuthenticatedUser:
        start_time = datetime.now(timezone.utc)

        try:
            # Check admin permission
            rbac_service.check_admin_permission(
                user_role=current_user.role, user_id=current_user.user_id, request=request
            )

            elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            logger.debug(
                "Admin check successful",
                extra={
                    "operation": "require_admin",
                    "user_id": current_user.user_id,
                    "user_role": current_user.role.value,
                    "elapsed_ms": elapsed_ms,
                    "endpoint": f"{request.method} {request.url.path}",
                },
            )

            return current_user

        except RBACError as e:
            # Log security event for admin access denial
            _log_rbac_security_event(db, request, current_user, "admin_required")
            raise

    return admin_dependency


def require_any_scope(*required_scopes: str) -> Callable:
    """
    Dependency to require any of the specified scopes (convenience function).

    Args:
        required_scopes: Required permission scopes (user needs at least one)

    Returns:
        AuthenticatedUser: Current authenticated user with at least one required scope
    """
    return require_scopes(*required_scopes, require_all=False)


def require_all_scopes(*required_scopes: str) -> Callable:
    """
    Dependency to require all of the specified scopes (convenience function).

    Args:
        required_scopes: Required permission scopes (user needs all)

    Returns:
        AuthenticatedUser: Current authenticated user with all required scopes
    """
    return require_scopes(*required_scopes, require_all=True)


# Commonly used permission combinations for convenience


def require_read_access() -> Callable:
    """Dependency for basic read access to resources."""
    return require_auth()


def require_write_access() -> Callable:
    """Dependency for write access to resources."""
    return require_role(UserRole.OPERATOR)


def require_delete_access() -> Callable:
    """Dependency for delete access to resources."""
    return require_role(UserRole.ENGINEER)


def require_model_create() -> Callable:
    """Dependency for model creation permissions."""
    return require_scopes("models:create")


def require_model_write() -> Callable:
    """Dependency for model write permissions."""
    return require_scopes("models:write")


def require_model_delete() -> Callable:
    """Dependency for model delete permissions."""
    return require_scopes("models:delete")


def require_admin_users() -> Callable:
    """Dependency for admin user management permissions."""
    return require_scopes("admin:users")


def require_system_admin() -> Callable:
    """Dependency for system administration permissions."""
    return require_scopes("admin:system")


# Optional authentication for public/semi-public endpoints


def optional_auth() -> Callable:
    """
    Dependency for optional authentication (allows anonymous access).

    Returns:
        Optional[AuthenticatedUser]: Current authenticated user or None
    """

    async def optional_auth_dependency(
        request: Request,
        current_user: Optional[AuthenticatedUser] = Depends(get_current_user_optional),
        db: DBSession = Depends(get_db),
    ) -> Optional[AuthenticatedUser]:
        if current_user:
            try:
                # Check user account status if authenticated
                rbac_service.check_user_active(current_user.user, request)

                logger.debug(
                    "Optional authentication successful",
                    extra={
                        "operation": "optional_auth",
                        "user_id": current_user.user_id,
                        "role": current_user.role.value,
                        "endpoint": f"{request.method} {request.url.path}",
                    },
                )

                return current_user

            except RBACError:
                # Return None for inactive accounts in optional auth
                logger.info(
                    "Optional authentication failed - inactive account",
                    extra={
                        "operation": "optional_auth",
                        "user_id": current_user.user_id,
                        "endpoint": f"{request.method} {request.url.path}",
                    },
                )
                return None

        return None

    return optional_auth_dependency


# Legacy compatibility (for gradual migration)


def get_current_user_legacy(*args, **kwargs):
    """Legacy function for backward compatibility during migration."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Legacy authentication disabled. Use new RBAC dependencies.",
    )
