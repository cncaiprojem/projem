"""
Ultra Enterprise CSRF Middleware for Task 3.8
Banking-level CSRF Double-Submit Cookie Protection Middleware

This middleware implements:
- Automatic CSRF token validation for state-changing requests
- Browser detection for selective protection
- Integration with existing authentication system (Task 3.3)
- Turkish KVKV compliant error responses
- Comprehensive security event logging

Risk Assessment: CRITICAL - Prevents CSRF attacks on authenticated endpoints
Compliance: KVKV Article 6, GDPR Article 25, ISO 27001 A.14.2.5
Security Level: Ultra-Enterprise Banking Grade
"""

from __future__ import annotations

import time
from typing import Callable, Optional

from fastapi import Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response as StarletteResponse

from ..db import get_db
from ..services.csrf_service import csrf_service, CSRFValidationResult
from ..core.logging import get_logger
from ..core.settings import ultra_enterprise_settings
from ..core.environment import environment

logger = get_logger(__name__)


class CSRFProtectionMiddleware(BaseHTTPMiddleware):
    """
    Ultra Enterprise CSRF Protection Middleware

    **Protection Strategy:**
    - Double-submit cookie validation for browser requests
    - Selective protection based on request method and client type
    - Integration with Authorization header authentication
    - Turkish localized error messages for KVKV compliance

    **Bypass Conditions:**
    - Safe HTTP methods (GET, HEAD, OPTIONS)
    - Non-browser clients (no cookies)
    - Unauthenticated requests (optional based on configuration)
    - Internal API calls (specific user agents)

    **Security Events:**
    - All CSRF validation failures are logged
    - Rate limiting violations are tracked
    - Suspicious patterns trigger additional logging
    """

    def __init__(self, app, require_auth_for_csrf: Optional[bool] = None):
        """
        Initialize CSRF protection middleware.

        Args:
            app: FastAPI application instance
            require_auth_for_csrf: Whether to require authentication for CSRF protection
                                 (defaults to setting value if not provided)
        """
        super().__init__(app)
        self.require_auth_for_csrf = (
            require_auth_for_csrf
            if require_auth_for_csrf is not None
            else getattr(ultra_enterprise_settings, "CSRF_REQUIRE_AUTH", True)
        )

        # Paths that are exempt from CSRF protection
        self.exempt_paths = {
            "/api/v1/auth/csrf-token",  # CSRF token endpoint itself
            "/docs",  # API documentation
            "/openapi.json",  # OpenAPI schema
            "/healthz",  # Health check
            "/metrics",  # Monitoring metrics
            "/static/",  # Static files
        }

        # User agents that are exempt (internal services)
        self.exempt_user_agents = {
            "health-check",
            "monitoring",
            "internal-service",
            "docker-compose",
        }

    async def dispatch(self, request: Request, call_next: Callable) -> StarletteResponse:
        """
        Process request through CSRF protection middleware.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware or route handler

        Returns:
            HTTP response
        """
        start_time = time.time()

        # Skip CSRF protection for exempt paths
        if self._is_path_exempt(request.url.path):
            return await call_next(request)

        # Skip CSRF protection for exempt user agents
        user_agent = request.headers.get("User-Agent", "").lower()
        if any(exempt_ua in user_agent for exempt_ua in self.exempt_user_agents):
            logger.debug(
                "CSRF protection bypassed for exempt user agent",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "user_agent": user_agent[:50],
                },
            )
            return await call_next(request)

        # Task 3.12: Dev-mode localhost bypass (DEVELOPMENT ONLY)
        if (
            environment.is_development
            and environment.is_dev_mode
            and environment.CSRF_DEV_LOCALHOST_BYPASS
            and hasattr(request.state, "dev_csrf_localhost_bypass")
            and request.state.dev_csrf_localhost_bypass
        ):
            logger.debug(
                "CSRF protection bypassed for localhost in dev mode",
                extra={
                    "operation": "csrf_dev_localhost_bypass",
                    "path": request.url.path,
                    "method": request.method,
                    "environment": str(environment.ENV),
                    "warning": "CSRF bypass active for localhost in development mode only",
                },
            )
            return await call_next(request)

        # Get database connection for logging
        db = None
        try:
            db = next(get_db())

            # Extract user ID from Authorization header if present
            user_id = self._extract_user_id_from_auth(request)

            # Validate CSRF token
            validation_result = csrf_service.validate_csrf_token(
                db=db, request=request, user_id=user_id, require_auth=self.require_auth_for_csrf
            )

            # Handle validation failure
            if validation_result != CSRFValidationResult.VALID:
                processing_time_ms = int((time.time() - start_time) * 1000)

                logger.warning(
                    "CSRF protection blocked request",
                    extra={
                        "operation": "csrf_protection_blocked",
                        "path": request.url.path,
                        "method": request.method,
                        "user_id": user_id,
                        "validation_result": validation_result.value,
                        "processing_time_ms": processing_time_ms,
                        "ip_address": self._get_client_ip(request),
                        "user_agent": request.headers.get("User-Agent", "")[:100],
                    },
                )

                # Create Turkish localized error response
                error_response = csrf_service.create_csrf_error_response(validation_result)

                # Add security headers to error response
                response = JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN, content=error_response
                )
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["X-Frame-Options"] = "DENY"
                response.headers["X-XSS-Protection"] = "1; mode=block"

                if db:
                    db.commit()

                return response

            # CSRF validation passed - continue to next middleware/handler
            logger.debug(
                "CSRF protection passed",
                extra={
                    "operation": "csrf_protection_passed",
                    "path": request.url.path,
                    "method": request.method,
                    "user_id": user_id,
                    "processing_time_ms": int((time.time() - start_time) * 1000),
                },
            )

            if db:
                db.commit()

            return await call_next(request)

        except Exception as e:
            logger.error(
                "CSRF middleware error",
                exc_info=True,
                extra={
                    "operation": "csrf_middleware_error",
                    "path": request.url.path,
                    "method": request.method,
                    "error_type": type(e).__name__,
                },
            )

            if db:
                try:
                    db.rollback()
                except Exception:
                    pass

            # On middleware error, deny request for security
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error_code": "ERR-CSRF-MIDDLEWARE-ERROR",
                    "message": "Güvenlik kontrolü hatası",
                    "details": {
                        "tr": "Güvenlik kontrolü sırasında bir hata oluştu.",
                        "en": "Error occurred during security check.",
                    },
                },
            )
        finally:
            if db:
                try:
                    db.close()
                except Exception:
                    pass

    def _is_path_exempt(self, path: str) -> bool:
        """
        Check if path is exempt from CSRF protection.

        Args:
            path: Request path

        Returns:
            True if path is exempt
        """
        return any(exempt_path in path for exempt_path in self.exempt_paths)

    def _extract_user_id_from_auth(self, request: Request) -> Optional[int]:
        """
        Extract user ID from Authorization header (simplified).

        In production, this would properly decode the JWT token.
        For now, we return None and rely on the service layer.

        Args:
            request: HTTP request

        Returns:
            User ID if available, None otherwise
        """
        # TODO: Implement proper JWT token decoding
        # For now, we let the service layer handle user identification
        return None

    def _get_client_ip(self, request: Request) -> Optional[str]:
        """
        Extract client IP address from request.

        Args:
            request: HTTP request

        Returns:
            Client IP address
        """
        # Check for proxy headers first
        if "x-forwarded-for" in request.headers:
            return request.headers["x-forwarded-for"].split(",")[0].strip()
        elif "x-real-ip" in request.headers:
            return request.headers["x-real-ip"]
        else:
            return getattr(request.client, "host", None)


class CSRFDependency:
    """
    CSRF protection dependency for specific endpoints.

    Use this dependency in route handlers that need explicit CSRF protection:

    ```python
    @router.post("/sensitive-action")
    async def sensitive_action(
        request: Request,
        db: Session = Depends(get_db),
        _csrf_check: None = Depends(csrf_protection)
    ):
        # Your route logic here
    ```
    """

    def __init__(self, require_auth: bool = True):
        """
        Initialize CSRF dependency.

        Args:
            require_auth: Whether authentication is required for CSRF protection
        """
        self.require_auth = require_auth

    async def __call__(self, request: Request, db: Session) -> None:
        """
        Validate CSRF token for this request.

        Args:
            request: HTTP request
            db: Database session

        Raises:
            HTTPException: If CSRF validation fails
        """
        try:
            # Extract user ID (simplified - in production decode JWT)
            user_id = None

            # Validate CSRF token
            validation_result = csrf_service.validate_csrf_token(
                db=db, request=request, user_id=user_id, require_auth=self.require_auth
            )

            if validation_result != CSRFValidationResult.VALID:
                error_response = csrf_service.create_csrf_error_response(validation_result)

                logger.warning(
                    "CSRF dependency blocked request",
                    extra={
                        "operation": "csrf_dependency_blocked",
                        "path": request.url.path,
                        "method": request.method,
                        "validation_result": validation_result.value,
                    },
                )

                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_response)

        except HTTPException:
            raise
        except Exception as e:
            logger.error(
                "CSRF dependency error",
                exc_info=True,
                extra={
                    "operation": "csrf_dependency_error",
                    "path": request.url.path,
                    "method": request.method,
                    "error_type": type(e).__name__,
                },
            )

            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error_code": "ERR-CSRF-DEPENDENCY-ERROR",
                    "message": "CSRF kontrolü hatası",
                    "details": {
                        "tr": "CSRF güvenlik kontrolü sırasında hata oluştu.",
                        "en": "Error occurred during CSRF security check.",
                    },
                },
            )


# Global dependency instances
csrf_protection = CSRFDependency(require_auth=True)
csrf_protection_no_auth = CSRFDependency(require_auth=False)
