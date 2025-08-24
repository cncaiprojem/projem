"""
Ultra Enterprise JWT Middleware for Task 3.3

This middleware implements banking-level JWT authentication with:
- Bearer token validation for protected routes
- Automatic session correlation and validation
- Comprehensive error handling with Turkish localization
- Security audit logging for authentication events
- Performance optimized token verification
- Integration with existing session management
"""

from typing import Optional, List, Callable, Any
from datetime import datetime, timezone

from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session as DBSession

from ..models.user import User
from ..models.session import Session
from ..services.jwt_service import jwt_service, JWTError, JWTErrorCode, JWTClaims
from ..core.logging import get_logger
from ..db import get_db

logger = get_logger(__name__)


class JWTAuthenticationError(HTTPException):
    """JWT authentication error with Turkish localization."""
    
    def __init__(self, code: str, message: str, details: Optional[dict] = None):
        self.code = code
        self.details = details or {}
        
        # Map error codes to HTTP status codes
        status_mapping = {
            JWTErrorCode.TOKEN_INVALID: status.HTTP_401_UNAUTHORIZED,
            JWTErrorCode.TOKEN_EXPIRED: status.HTTP_401_UNAUTHORIZED,
            JWTErrorCode.TOKEN_REVOKED: status.HTTP_401_UNAUTHORIZED,
            JWTErrorCode.TOKEN_MALFORMED: status.HTTP_400_BAD_REQUEST,
            JWTErrorCode.TOKEN_MISSING_CLAIMS: status.HTTP_401_UNAUTHORIZED,
            JWTErrorCode.TOKEN_INVALID_SIGNATURE: status.HTTP_401_UNAUTHORIZED,
            JWTErrorCode.TOKEN_WRONG_ALGORITHM: status.HTTP_401_UNAUTHORIZED,
            JWTErrorCode.SESSION_NOT_FOUND: status.HTTP_401_UNAUTHORIZED,
        }
        
        super().__init__(
            status_code=status_mapping.get(code, status.HTTP_401_UNAUTHORIZED),
            detail={
                'error_code': code,
                'message': message,
                'details': self.details
            }
        )


class AuthenticatedUser:
    """Authenticated user information from JWT token."""
    
    def __init__(self, user: User, session: Session, claims: JWTClaims):
        self.user = user
        self.session = session
        self.claims = claims
        
        # Convenience properties
        self.user_id = user.id
        self.email = user.email
        self.role = user.role
        self.session_id = session.id
        self.scopes = claims.scopes
        # Task 7.1: Add license and tenant tracking
        self.license_id = claims.license_id
        self.tenant_id = claims.tenant_id
    
    def has_scope(self, scope: str) -> bool:
        """Check if user has specific scope permission."""
        return scope in self.scopes
    
    def has_any_scope(self, scopes: List[str]) -> bool:
        """Check if user has any of the specified scopes."""
        return any(scope in self.scopes for scope in scopes)
    
    def has_all_scopes(self, scopes: List[str]) -> bool:
        """Check if user has all of the specified scopes."""
        return all(scope in self.scopes for scope in scopes)
    
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return str(self.role).lower() == 'admin'
    
    def can_write(self) -> bool:
        """Check if user has write permissions."""
        return self.has_scope('write') or self.is_admin()
    
    def can_delete(self) -> bool:
        """Check if user has delete permissions."""
        return self.has_scope('delete') or self.is_admin()


# FastAPI security scheme for Bearer tokens
jwt_bearer_scheme = HTTPBearer(
    scheme_name="JWT Bearer",
    description="JWT access token in Authorization header",
    auto_error=False
)


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(jwt_bearer_scheme),
    db: DBSession = Depends(get_db)
) -> Optional[AuthenticatedUser]:
    """
    Get current authenticated user from JWT token (optional).
    Returns None if no token provided or token is invalid.
    
    Args:
        credentials: Bearer token credentials
        db: Database session
        
    Returns:
        AuthenticatedUser object or None
    """
    if not credentials:
        return None
    
    try:
        return _authenticate_user(credentials.credentials, db)
    except JWTAuthenticationError:
        return None
    except Exception as e:
        logger.warning("Optional JWT authentication failed", extra={
            'operation': 'get_current_user_optional',
            'error_type': type(e).__name__,
            'has_credentials': bool(credentials)
        })
        return None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(jwt_bearer_scheme),
    db: DBSession = Depends(get_db)
) -> AuthenticatedUser:
    """
    Get current authenticated user from JWT token (required).
    Raises HTTP 401 if no token provided or token is invalid.
    
    Args:
        credentials: Bearer token credentials
        db: Database session
        
    Returns:
        AuthenticatedUser object
        
    Raises:
        JWTAuthenticationError: If authentication fails
    """
    if not credentials:
        raise JWTAuthenticationError(
            JWTErrorCode.TOKEN_INVALID,
            "Authorization header gerekli. Bearer token bulunamadı."
        )
    
    return _authenticate_user(credentials.credentials, db)


def require_scopes(*required_scopes: str) -> Callable:
    """
    Decorator to require specific scopes for endpoint access.
    
    Args:
        required_scopes: Required permission scopes
        
    Returns:
        Dependency function that validates scopes
    """
    def scope_dependency(
        current_user: AuthenticatedUser = Depends(get_current_user)
    ) -> AuthenticatedUser:
        if not current_user.has_all_scopes(list(required_scopes)):
            logger.warning("Insufficient scopes for endpoint access", extra={
                'operation': 'require_scopes',
                'user_id': current_user.user_id,
                'user_scopes': current_user.scopes,
                'required_scopes': list(required_scopes)
            })
            
            raise JWTAuthenticationError(
                'ERR-INSUFFICIENT-SCOPES',
                f"Bu işlem için gerekli izinler: {', '.join(required_scopes)}",
                {
                    'required_scopes': list(required_scopes),
                    'user_scopes': current_user.scopes
                }
            )
        
        return current_user
    
    return scope_dependency


def require_admin() -> Callable:
    """
    Decorator to require admin role for endpoint access.
    
    Returns:
        Dependency function that validates admin role
    """
    def admin_dependency(
        current_user: AuthenticatedUser = Depends(get_current_user)
    ) -> AuthenticatedUser:
        if not current_user.is_admin():
            logger.warning("Admin access denied for non-admin user", extra={
                'operation': 'require_admin',
                'user_id': current_user.user_id,
                'user_role': str(current_user.role)
            })
            
            raise JWTAuthenticationError(
                'ERR-ADMIN-REQUIRED',
                "Bu işlem için admin yetkisi gereklidir",
                {'user_role': str(current_user.role)}
            )
        
        return current_user
    
    return admin_dependency


def _authenticate_user(token: str, db: DBSession) -> AuthenticatedUser:
    """
    Internal function to authenticate user from JWT token.
    
    Args:
        token: JWT access token
        db: Database session
        
    Returns:
        AuthenticatedUser object
        
    Raises:
        JWTAuthenticationError: If authentication fails
    """
    start_time = datetime.now(timezone.utc)
    
    try:
        # Verify JWT token and get claims
        claims = jwt_service.verify_access_token(token, db)
        
        # Get user from database
        user = db.query(User).filter(User.id == int(claims.sub)).first()
        if not user:
            raise JWTAuthenticationError(
                'ERR-USER-NOT-FOUND',
                "Token'da belirtilen kullanıcı bulunamadı"
            )
        
        # Verify user is still active
        if not user.is_active:
            raise JWTAuthenticationError(
                'ERR-USER-INACTIVE',
                "Kullanıcı hesabı aktif değil"
            )
        
        # Get session from database (should be cached from JWT verification)
        session = db.query(Session).filter(Session.id == claims.sid).first()
        if not session:
            raise JWTAuthenticationError(
                JWTErrorCode.SESSION_NOT_FOUND,
                "Token'a bağlı oturum bulunamadı"
            )
        
        elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        
        # Log successful authentication
        logger.info("JWT authentication successful", extra={
            'operation': 'jwt_authenticate_user',
            'user_id': user.id,
            'session_id': str(session.id),
            'token_id': claims.jti,
            'scopes': claims.scopes,
            'elapsed_ms': elapsed_ms
        })
        
        return AuthenticatedUser(user, session, claims)
        
    except JWTError as e:
        # Convert JWT service errors to authentication errors
        raise JWTAuthenticationError(e.code, e.message, e.details)
    
    except JWTAuthenticationError:
        raise  # Re-raise authentication errors
    
    except Exception as e:
        logger.error("JWT authentication failed", exc_info=True, extra={
            'operation': 'jwt_authenticate_user',
            'error_type': type(e).__name__,
            'token_preview': token[:20] + '...' if len(token) > 20 else token
        })
        
        raise JWTAuthenticationError(
            'ERR-AUTH-FAILED',
            "Kimlik doğrulama başarısız",
            {'error_type': type(e).__name__}
        )


# Additional utility functions for specific use cases

def get_user_with_write_access(
    current_user: AuthenticatedUser = Depends(get_current_user)
) -> AuthenticatedUser:
    """Get current user with write access validation."""
    if not current_user.can_write():
        raise JWTAuthenticationError(
            'ERR-WRITE-ACCESS-DENIED',
            "Bu işlem için yazma yetkisi gereklidir",
            {'user_scopes': current_user.scopes}
        )
    return current_user


def get_user_with_delete_access(
    current_user: AuthenticatedUser = Depends(get_current_user)
) -> AuthenticatedUser:
    """Get current user with delete access validation."""
    if not current_user.can_delete():
        raise JWTAuthenticationError(
            'ERR-DELETE-ACCESS-DENIED',
            "Bu işlem için silme yetkisi gereklidir",
            {'user_scopes': current_user.scopes}
        )
    return current_user


def get_admin_user(
    current_user: AuthenticatedUser = Depends(require_admin())
) -> AuthenticatedUser:
    """Get current user with admin role validation."""
    return current_user


# Legacy compatibility functions (will be deprecated)
def get_current_user_legacy(*args, **kwargs):
    """Legacy function for backward compatibility during migration."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Legacy authentication disabled. Use new JWT middleware."
    )