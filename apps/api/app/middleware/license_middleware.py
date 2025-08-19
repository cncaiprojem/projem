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

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, Set, Optional, Callable, Tuple, Any
import threading
from contextlib import contextmanager

from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError, OperationalError

from ..db import get_db, db_session
from ..middleware.jwt_middleware import _authenticate_user, jwt_bearer_scheme
from ..services.license_service import LicenseService
from ..services.session_service import SessionService
from ..services.audit_service import audit_service
from ..services.pii_masking_service import pii_masking_service, MaskingLevel
from ..core.logging import get_logger

logger = get_logger(__name__)

# Thread-safe tracking of (user_id, license_id) tuples who have been processed for license expiry
# Using tuple key to handle multiple license expirations for same user correctly
_license_expiry_processed: Set[Tuple[int, uuid.UUID]] = set()
_license_expiry_lock = threading.Lock()

# Session service instance for revocation
session_service = SessionService()


class LicenseExpiredError(Exception):
    """Exception raised when license is expired."""
    
    def __init__(self, user_id: int, expired_at: datetime):
        self.user_id = user_id
        self.expired_at = expired_at
        super().__init__(f"License expired for user {user_id} at {expired_at}")


@contextmanager
def get_db_session_for_middleware():
    """
    Dedicated synchronous context manager for database sessions in middleware.
    Provides proper session management with guaranteed cleanup and rollback.
    
    ENHANCED: Per review feedback, improved error handling and session lifecycle management
    to ensure no session leaks even in extreme error conditions.
    
    This is a synchronous function because SQLAlchemy sessions are synchronous.
    Using async context manager with sync session was causing runtime errors.
    """
    session = None
    session_id = str(uuid.uuid4())[:8]  # Short ID for tracking in logs
    
    try:
        logger.debug(
            f"Creating database session for middleware",
            extra={
                "operation": "get_db_session_for_middleware",
                "session_id": session_id,
                "action": "create"
            }
        )
        
        # Use the db_session context manager from db.py
        with db_session() as session:
            # Track session creation
            logger.debug(
                f"Database session created successfully",
                extra={
                    "operation": "get_db_session_for_middleware",
                    "session_id": session_id,
                    "action": "created"
                }
            )
            yield session
            
    except (SQLAlchemyError, OperationalError) as e:
        logger.error(
            "Database session error in middleware",
            exc_info=True,
            extra={
                "operation": "get_db_session_for_middleware",
                "session_id": session_id,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "action": "error"
            }
        )
        # Session rollback is handled by db_session context manager
        raise
        
    except Exception as e:
        logger.error(
            "Unexpected error in database session",
            exc_info=True,
            extra={
                "operation": "get_db_session_for_middleware",
                "session_id": session_id,
                "error_type": type(e).__name__,
                "action": "unexpected_error"
            }
        )
        # Session rollback is handled by db_session context manager
        raise
        
    finally:
        # The db_session context manager handles closing
        # We just log for monitoring
        logger.debug(
            f"Database session context completed",
            extra={
                "operation": "get_db_session_for_middleware",
                "session_id": session_id,
                "action": "complete"
            }
        )


async def get_current_user_from_request(request: Request) -> Optional[int]:
    """
    Extract authenticated user ID from request with proper error handling.
    Returns user ID if authenticated, None otherwise.
    
    Args:
        request: FastAPI request object
        
    Returns:
        User ID if authenticated, None otherwise
    """
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    
    try:
        # Extract authorization header
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            logger.debug(
                "No bearer token in authorization header",
                extra={
                    "operation": "get_current_user_from_request",
                    "correlation_id": correlation_id,
                    "has_auth_header": bool(auth_header)
                }
            )
            return None
        
        # Get token from header
        token = auth_header[7:]  # Remove "Bearer " prefix
        
        # Validate token format
        if not token or len(token) < 10:
            logger.warning(
                "Invalid token format",
                extra={
                    "operation": "get_current_user_from_request",
                    "correlation_id": correlation_id,
                    "token_length": len(token) if token else 0
                }
            )
            return None
        
        # Use dedicated context manager for database session
        with get_db_session_for_middleware() as db:
            try:
                # Authenticate user using JWT middleware logic
                authenticated_user = _authenticate_user(token, db)
                
                if not authenticated_user:
                    logger.debug(
                        "Token authentication failed",
                        extra={
                            "operation": "get_current_user_from_request",
                            "correlation_id": correlation_id
                        }
                    )
                    return None
                
                logger.debug(
                    "User authenticated successfully",
                    extra={
                        "operation": "get_current_user_from_request",
                        "correlation_id": correlation_id,
                        "user_id": authenticated_user.user_id
                    }
                )
                
                return authenticated_user.user_id
                
            except (ValueError, KeyError) as e:
                logger.warning(
                    "Token validation error",
                    extra={
                        "operation": "get_current_user_from_request",
                        "correlation_id": correlation_id,
                        "error_type": type(e).__name__,
                        "error_message": str(e)
                    }
                )
                return None
                
    except SQLAlchemyError as e:
        logger.error(
            "Database error during user authentication",
            exc_info=True,
            extra={
                "operation": "get_current_user_from_request",
                "correlation_id": correlation_id,
                "error_type": type(e).__name__
            }
        )
        return None
        
    except Exception as e:
        logger.error(
            "Unexpected error extracting user from request",
            exc_info=True,
            extra={
                "operation": "get_current_user_from_request",
                "correlation_id": correlation_id,
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
    
    def _get_client_info(self, request: Request) -> Tuple[str, str]:
        """
        Extract client IP and user agent for audit purposes.
        Uses shared PII masking service for consistent anonymization.
        
        Args:
            request: FastAPI request object
            
        Returns:
            Tuple of (masked_ip, user_agent)
        """
        # Get raw IP address
        client_ip = request.client.host if request.client else "unknown"
        
        # Use shared PII masking service for KVKK compliance
        # Using MEDIUM level as per KVKK recommendations (masks last 2 octets)
        if client_ip and client_ip != "unknown":
            try:
                masked_ip = pii_masking_service.mask_ip_address(
                    client_ip, 
                    MaskingLevel.MEDIUM
                )
            except Exception as e:
                logger.warning(
                    "Failed to mask IP address, using fallback",
                    extra={
                        "operation": "_get_client_info",
                        "error_type": type(e).__name__,
                        "original_ip_prefix": client_ip.split('.')[0] if '.' in client_ip else client_ip[:4]
                    }
                )
                # Fallback to simple masking if service fails
                masked_ip = "***.***.***.**"
        else:
            masked_ip = client_ip
        
        # Extract and sanitize user agent
        user_agent = request.headers.get("user-agent", "unknown")
        if user_agent:
            # Truncate for storage and security
            user_agent = user_agent[:200]
            # Remove any potential injection attempts
            user_agent = user_agent.replace('\n', ' ').replace('\r', ' ')
        
        return masked_ip, user_agent
    
    async def _revoke_user_sessions_on_expiry(
        self, 
        db: Session, 
        user_id: int,
        license_id: uuid.UUID,
        client_ip: str,
        user_agent: str,
        request_id: str
    ) -> bool:
        """
        Revoke all user sessions when license expires.
        
        ULTRA-ENTERPRISE THREAD SAFETY:
        - Uses (user_id, license_id) tuple as tracking key for precise control
        - Thread-safe with global lock ensuring atomic check-and-set
        - Handles multiple licenses per user correctly
        - Removes from tracking on failure to allow retry
        - Banking-grade idempotency guaranteed
        
        Args:
            db: Database session
            user_id: User whose sessions to revoke
            license_id: License that expired
            client_ip: Masked client IP for audit (KVKK compliant)
            user_agent: Client user agent (sanitized)
            request_id: Request correlation ID for tracing
            
        Returns:
            True if sessions were revoked or already processed, False on error
            
        Thread Safety Guarantees:
            - Exactly-once processing per (user, license) pair
            - No race conditions between concurrent requests
            - Automatic retry capability on transient failures
        """
        # Validate inputs for defensive programming
        if not user_id or not license_id:
            logger.error(
                "Invalid parameters for session revocation",
                extra={
                    "operation": "license_expiry_invalid_params",
                    "user_id": user_id,
                    "license_id": str(license_id) if license_id else None,
                    "request_id": request_id
                }
            )
            return False
        
        # Create tracking key as (user_id, license_id) tuple
        # This allows handling multiple license expirations per user
        tracking_key = (user_id, license_id)
        
        # Thread-safe check if this user+license has already been processed
        with _license_expiry_lock:
            if tracking_key in _license_expiry_processed:
                logger.info(
                    "User sessions already revoked for this expired license (idempotent)",
                    extra={
                        "operation": "license_expiry_sessions_already_revoked",
                        "user_id": user_id,
                        "license_id": str(license_id),
                        "request_id": request_id,
                        "tracking_key": f"{user_id}:{license_id}",
                        "tracking_set_size": len(_license_expiry_processed)
                    }
                )
                return True
            
            # Mark user+license as being processed (atomic operation)
            _license_expiry_processed.add(tracking_key)
            logger.debug(
                "Marked license expiry for processing",
                extra={
                    "operation": "license_expiry_mark_processing",
                    "user_id": user_id,
                    "license_id": str(license_id),
                    "tracking_key": f"{user_id}:{license_id}",
                    "tracking_set_size": len(_license_expiry_processed)
                }
            )
        
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
                    "license_id": str(license_id),
                    "ip_address": client_ip,
                    "user_agent": user_agent,
                    "request_id": request_id
                },
                metadata={
                    "compliance": "kvkk_audit_trail",
                    "security_action": "session_revocation",
                    "automated_action": True,
                    "tracking_key": f"{user_id}:{license_id}"
                }
            )
            
            logger.warning(
                "All user sessions revoked due to license expiry",
                extra={
                    "operation": "license_expiry_sessions_revoked",
                    "user_id": user_id,
                    "license_id": str(license_id),
                    "revoked_sessions_count": revoked_count,
                    "request_id": request_id,
                    "tracking_key": f"{user_id}:{license_id}"
                }
            )
            
            db.commit()
            return True
            
        except (IntegrityError, OperationalError) as e:
            db.rollback()
            logger.error(
                "Database error while revoking sessions on license expiry",
                exc_info=True,
                extra={
                    "operation": "license_expiry_session_revocation_db_error",
                    "user_id": user_id,
                    "license_id": str(license_id),
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "request_id": request_id
                }
            )
            # Remove from processed set so it can be retried
            with _license_expiry_lock:
                _license_expiry_processed.discard(tracking_key)
            return False
            
        except Exception as e:
            db.rollback()
            logger.error(
                "Unexpected error revoking sessions on license expiry",
                exc_info=True,
                extra={
                    "operation": "license_expiry_session_revocation_failed",
                    "user_id": user_id,
                    "license_id": str(license_id),
                    "error_type": type(e).__name__,
                    "request_id": request_id
                }
            )
            # Remove from processed set so it can be retried
            with _license_expiry_lock:
                _license_expiry_processed.discard(tracking_key)
            return False
    
    async def _check_license_and_enforce(
        self, 
        request: Request, 
        user_id: int,
        request_id: str
    ) -> Optional[JSONResponse]:
        """
        Check user license and enforce restrictions with proper error handling.
        Returns error response if license is invalid, None if valid.
        
        Args:
            request: FastAPI request object
            user_id: User ID to check license for
            request_id: Request correlation ID
            
        Returns:
            JSONResponse with error if license invalid, None if valid
        """
        client_ip, user_agent = self._get_client_info(request)
        
        try:
            # Use dedicated context manager for database session
            with get_db_session_for_middleware() as db:
                try:
                    # Get user's active license with proper error handling
                    license = LicenseService.get_active_license(db, user_id)
                except Exception as e:
                    # Handle license service errors
                    logger.error(
                        "Error retrieving license",
                        exc_info=True,
                        extra={
                            "operation": "license_guard_get_license_error",
                            "user_id": user_id,
                            "error_type": type(e).__name__,
                            "request_id": request_id
                        }
                    )
                    raise
                
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
                            "license_id": str(license.id),
                            "expired_at": license.ends_at.isoformat(),
                            "request_id": request_id,
                            "path": str(request.url.path)
                        }
                    )
                    
                    # Trigger session revocation with license_id
                    await self._revoke_user_sessions_on_expiry(
                        db, user_id, license.id, client_ip, user_agent, request_id
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
                        "license_id": str(license.id),
                        "expires_at": license.ends_at.isoformat(),
                        "request_id": request_id
                    }
                )
                
                return None  # License is valid, allow request to proceed
                
        except (SQLAlchemyError, OperationalError) as e:
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
def clear_license_expiry_cache() -> None:
    """
    Clear the license expiry processed cache.
    Used for testing or administrative purposes.
    """
    with _license_expiry_lock:
        count = len(_license_expiry_processed)
        _license_expiry_processed.clear()
    logger.info(
        "License expiry cache cleared",
        extra={
            "operation": "clear_license_expiry_cache",
            "cleared_count": count
        }
    )


# Utility function to check if user+license is in processed cache
def is_license_expiry_processed(user_id: int, license_id: uuid.UUID) -> bool:
    """
    Check if a specific user+license expiry has been processed.
    
    Args:
        user_id: User ID to check
        license_id: License ID to check
        
    Returns:
        True if this user+license combination has been processed
    """
    tracking_key = (user_id, license_id)
    with _license_expiry_lock:
        return tracking_key in _license_expiry_processed


# Backward compatibility wrapper
def is_user_license_expiry_processed(user_id: int) -> bool:
    """
    Check if any license expiry for this user has been processed.
    Provided for backward compatibility - prefer is_license_expiry_processed.
    
    Args:
        user_id: User ID to check
        
    Returns:
        True if any license for this user has been processed
    """
    with _license_expiry_lock:
        return any(key[0] == user_id for key in _license_expiry_processed)