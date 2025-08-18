"""
Task 4.3: License Guard Middleware
Ultra-Enterprise License Enforcement with Session Revocation on Expiry

This middleware implements:
1. Global license enforcement for protected routes
2. Session revocation when license expires
3. Turkish KVKK compliance 
4. Thread-safe single revocation per user
5. Banking-grade security standards
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, Set, Optional, Callable
import threading
from contextlib import asynccontextmanager

from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from ..db import get_db
from ..middleware.jwt_middleware import _authenticate_user, jwt_bearer_scheme
from ..services.license_service import LicenseService
from ..services.session_service import SessionService
from ..services.audit_service import audit_service
from ..core.logging import get_logger

logger = get_logger(__name__)

# Thread-safe tracking of users who have been processed for license expiry
_license_expiry_processed: Set[int] = set()
_license_expiry_lock = threading.Lock()

# Session service instance for revocation
session_service = SessionService()


class LicenseExpiredError(Exception):
    """Exception raised when license is expired."""
    
    def __init__(self, user_id: int, expired_at: datetime):
        self.user_id = user_id
        self.expired_at = expired_at
        super().__init__(f"License expired for user {user_id} at {expired_at}")


async def get_current_user_from_request(request: Request) -> Optional[int]:
    """
    Extract authenticated user ID from request.
    Returns user ID if authenticated, None otherwise.
    """
    try:
        # Extract authorization header
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        
        # Get token from header
        token = auth_header[7:]  # Remove "Bearer " prefix
        
        # Get database session
        db_gen = get_db()
        db = next(db_gen)
        
        try:
            # Authenticate user using JWT middleware logic
            authenticated_user = _authenticate_user(token, db)
            return authenticated_user.user_id
        finally:
            try:
                db.close()
            except Exception:
                pass
                
    except Exception as e:
        logger.debug(
            "Failed to extract user from request",
            extra={
                "operation": "get_current_user_from_request",
                "error_type": type(e).__name__
            }
        )
        return None


class LicenseGuardMiddleware(BaseHTTPMiddleware):
    """
    Ultra-Enterprise License Guard Middleware
    
    Enforces license requirements on protected routes and handles
    session revocation when licenses expire.
    """
    
    def __init__(self, app, excluded_paths: Optional[list] = None):
        super().__init__(app)
        # Default excluded paths - these should not require license checks
        self.excluded_paths = excluded_paths or [
            "/api/v1/auth",
            "/api/v1/health",
            "/webhooks",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/",
            "/api/v1/license/me"  # Allow checking license status even when expired
        ]
        logger.info(
            "License Guard Middleware initialized",
            extra={
                "operation": "license_guard_init",
                "excluded_paths": self.excluded_paths
            }
        )
    
    def _is_path_excluded(self, path: str) -> bool:
        """Check if the request path should be excluded from license checks."""
        for excluded_path in self.excluded_paths:
            if path.startswith(excluded_path):
                return True
        return False
    
    def _anonymize_ip(self, ip_address: str) -> str:
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
    
    def _get_client_info(self, request: Request) -> tuple[str, str]:
        """Extract client IP and user agent for audit purposes."""
        # Get raw IP and anonymize it for KVKV compliance
        client_ip = request.client.host if request.client else "unknown"
        client_ip = self._anonymize_ip(client_ip)
        
        user_agent = request.headers.get("user-agent", "unknown")[:200]  # Truncate for storage
        return client_ip, user_agent
    
    async def _revoke_user_sessions_on_expiry(
        self, 
        db: Session, 
        user_id: int,
        client_ip: str,
        user_agent: str,
        request_id: str
    ) -> bool:
        """
        Revoke all user sessions when license expires.
        Thread-safe implementation to ensure single revocation per user.
        """
        # Check if this user has already been processed
        with _license_expiry_lock:
            if user_id in _license_expiry_processed:
                logger.info(
                    "User sessions already revoked for expired license",
                    extra={
                        "operation": "license_expiry_sessions_already_revoked",
                        "user_id": user_id,
                        "request_id": request_id
                    }
                )
                return True
            
            # Mark user as processed
            _license_expiry_processed.add(user_id)
        
        try:
            # Revoke all user sessions
            revoked_count = session_service.revoke_all_user_sessions(
                db=db,
                user_id=user_id,
                reason="license_expired",
                ip_address=client_ip,
                user_agent=user_agent
            )
            
            # Emit audit event for session revocation
            await audit_service.log_business_event(
                user_id=user_id,
                event_type="sessions_revoked_license_expired",
                details={
                    "revoked_sessions_count": revoked_count,
                    "reason": "license_expired",
                    "ip_address": client_ip,
                    "user_agent": user_agent,
                    "request_id": request_id
                },
                metadata={
                    "compliance": "kvkv_audit_trail",
                    "security_action": "session_revocation",
                    "automated_action": True
                }
            )
            
            logger.warning(
                "All user sessions revoked due to license expiry",
                extra={
                    "operation": "license_expiry_sessions_revoked",
                    "user_id": user_id,
                    "revoked_sessions_count": revoked_count,
                    "request_id": request_id
                }
            )
            
            db.commit()
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(
                "Failed to revoke user sessions on license expiry",
                exc_info=True,
                extra={
                    "operation": "license_expiry_session_revocation_failed",
                    "user_id": user_id,
                    "error_type": type(e).__name__,
                    "request_id": request_id
                }
            )
            # Remove from processed set so it can be retried
            with _license_expiry_lock:
                _license_expiry_processed.discard(user_id)
            return False
    
    async def _check_license_and_enforce(
        self, 
        request: Request, 
        user_id: int,
        request_id: str
    ) -> Optional[JSONResponse]:
        """
        Check user license and enforce restrictions.
        Returns error response if license is invalid, None if valid.
        """
        client_ip, user_agent = self._get_client_info(request)
        
        try:
            # Get database session
            db_gen = get_db()
            db = next(db_gen)
            
            try:
                # Get user's active license
                license = LicenseService.get_active_license(db, user_id)
                
                if not license:
                    # No active license found
                    logger.warning(
                        "Access denied - no active license",
                        extra={
                            "operation": "license_guard_no_license",
                            "user_id": user_id,
                            "request_id": request_id,
                            "path": str(request.url.path)
                        }
                    )
                    
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={
                            "error": "LIC_EXPIRED",
                            "message": "No active license found",
                            "message_tr": "Aktif lisans bulunamadı",
                            "detail": {
                                "code": "LIC_EXPIRED",
                                "reason": "no_active_license",
                                "user_id": user_id,
                                "timestamp": datetime.now(timezone.utc).isoformat()
                            }
                        }
                    )
                
                # Check if license is expired (additional safety check)
                now = datetime.now(timezone.utc)
                if license.ends_at <= now:
                    # License is expired - revoke sessions and deny access
                    logger.warning(
                        "Access denied - license expired",
                        extra={
                            "operation": "license_guard_expired",
                            "user_id": user_id,
                            "license_id": license.id,
                            "expired_at": license.ends_at.isoformat(),
                            "request_id": request_id,
                            "path": str(request.url.path)
                        }
                    )
                    
                    # Trigger session revocation
                    await self._revoke_user_sessions_on_expiry(
                        db, user_id, client_ip, user_agent, request_id
                    )
                    
                    return JSONResponse(
                        status_code=status.HTTP_403_FORBIDDEN,
                        content={
                            "error": "LIC_EXPIRED",
                            "message": "License has expired",
                            "message_tr": "Lisansın süresi dolmuş",
                            "detail": {
                                "code": "LIC_EXPIRED",
                                "reason": "license_expired", 
                                "expired_at": license.ends_at.isoformat(),
                                "user_id": user_id,
                                "timestamp": now.isoformat()
                            }
                        }
                    )
                
                # License is valid - log successful check
                logger.debug(
                    "License check passed",
                    extra={
                        "operation": "license_guard_valid",
                        "user_id": user_id,
                        "license_id": license.id,
                        "expires_at": license.ends_at.isoformat(),
                        "request_id": request_id
                    }
                )
                
                return None  # License is valid, allow request to proceed
                
            finally:
                # Always close the database session
                try:
                    db.close()
                except Exception:
                    pass
                
        except SQLAlchemyError as e:
            # Database error - fail closed (deny access)
            logger.error(
                "Database error during license check - failing closed",
                exc_info=True,
                extra={
                    "operation": "license_guard_db_error",
                    "user_id": user_id,
                    "error_type": type(e).__name__,
                    "request_id": request_id
                }
            )
            
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "error": "LIC_EXPIRED",
                    "message": "License verification unavailable",
                    "message_tr": "Lisans doğrulama hizmeti kullanılamıyor",
                    "detail": {
                        "code": "LIC_EXPIRED",
                        "reason": "verification_unavailable",
                        "user_id": user_id,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                }
            )
            
        except Exception as e:
            # Unexpected error - fail closed (deny access)
            logger.error(
                "Unexpected error during license check - failing closed",
                exc_info=True,
                extra={
                    "operation": "license_guard_unexpected_error",
                    "user_id": user_id,
                    "error_type": type(e).__name__,
                    "request_id": request_id
                }
            )
            
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "error": "LIC_EXPIRED",
                    "message": "License verification failed",
                    "message_tr": "Lisans doğrulama başarısız",
                    "detail": {
                        "code": "LIC_EXPIRED",
                        "reason": "verification_failed",
                        "user_id": user_id,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                }
            )
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Main middleware dispatch method."""
        request_id = str(uuid.uuid4())
        path = str(request.url.path)
        
        # Skip license check for excluded paths
        if self._is_path_excluded(path):
            logger.debug(
                "Skipping license check for excluded path",
                extra={
                    "operation": "license_guard_excluded",
                    "path": path,
                    "request_id": request_id
                }
            )
            return await call_next(request)
        
        try:
            # Extract current user from request
            current_user_id = await get_current_user_from_request(request)
            
            if not current_user_id:
                # No authenticated user - let auth middleware handle it
                logger.debug(
                    "No authenticated user found - skipping license check",
                    extra={
                        "operation": "license_guard_no_user",
                        "path": path,
                        "request_id": request_id
                    }
                )
                return await call_next(request)
            
            # Check license for authenticated user
            license_response = await self._check_license_and_enforce(
                request, current_user_id, request_id
            )
            
            if license_response:
                # License check failed - return error response
                return license_response
            
            # License is valid - proceed with request
            return await call_next(request)
            
        except Exception as e:
            # Unexpected error in middleware - fail closed
            logger.error(
                "Unexpected error in license guard middleware",
                exc_info=True,
                extra={
                    "operation": "license_guard_middleware_error",
                    "path": path,
                    "error_type": type(e).__name__,
                    "request_id": request_id
                }
            )
            
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "error": "LIC_EXPIRED",
                    "message": "License verification service unavailable",
                    "message_tr": "Lisans doğrulama servisi kullanılamıyor",
                    "detail": {
                        "code": "LIC_EXPIRED",
                        "reason": "service_unavailable",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                }
            )


# Utility function to clear processed users (for testing or admin purposes)
def clear_license_expiry_cache():
    """Clear the license expiry processed cache."""
    with _license_expiry_lock:
        _license_expiry_processed.clear()
    logger.info("License expiry cache cleared")


# Utility function to check if user is in processed cache
def is_user_license_expiry_processed(user_id: int) -> bool:
    """Check if user's license expiry has been processed."""
    with _license_expiry_lock:
        return user_id in _license_expiry_processed