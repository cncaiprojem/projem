"""
Ultra-Enterprise Correlation ID Middleware for Request Tracking
Task 3.11: Comprehensive request correlation with audit trail integration

Features:
- Automatic correlation ID generation/extraction
- Thread-safe context variable management
- Integration with audit logging and security events
- Turkish compliance headers
- Performance optimized for high-throughput systems
- Distributed tracing support
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ..core.logging import get_logger, request_id_ctx, user_id_ctx
from ..services.pii_masking_service import pii_masking_service, MaskingLevel


logger = get_logger(__name__)

# Context variables for request correlation
correlation_id_ctx: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
session_id_ctx: ContextVar[Optional[str]] = ContextVar("session_id", default=None)
request_start_time_ctx: ContextVar[Optional[float]] = ContextVar("request_start_time", default=None)


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Ultra-enterprise correlation ID middleware with audit integration."""

    def __init__(
        self,
        app: ASGIApp,
        header_name: str = "X-Correlation-ID",
        generate_if_missing: bool = True,
        include_response_header: bool = True,
        log_requests: bool = True,
        mask_sensitive_headers: bool = True,
    ):
        """Initialize correlation middleware.

        Args:
            app: ASGI application
            header_name: HTTP header name for correlation ID
            generate_if_missing: Generate new correlation ID if not provided
            include_response_header: Include correlation ID in response headers
            log_requests: Log request start/completion with correlation
            mask_sensitive_headers: Apply PII masking to logged headers
        """
        super().__init__(app)
        self.header_name = header_name
        self.generate_if_missing = generate_if_missing
        self.include_response_header = include_response_header
        self.log_requests = log_requests
        self.mask_sensitive_headers = mask_sensitive_headers

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with correlation ID tracking.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler in chain

        Returns:
            HTTP response with correlation headers
        """
        import time

        start_time = time.time()

        # Extract or generate correlation ID
        correlation_id = self._extract_correlation_id(request)

        # Extract session ID if available
        session_id = self._extract_session_id(request)

        # Set context variables for downstream use
        correlation_id_ctx.set(correlation_id)
        session_id_ctx.set(session_id)
        request_id_ctx.set(correlation_id)  # For logging compatibility
        request_start_time_ctx.set(start_time)

        # Extract and mask IP/User-Agent for audit logging
        client_ip = self._extract_client_ip(request)
        user_agent = request.headers.get("user-agent", "")

        masked_ip = (
            pii_masking_service.mask_ip_address(client_ip, MaskingLevel.MEDIUM)
            if client_ip
            else None
        )
        masked_ua = (
            pii_masking_service.mask_user_agent(user_agent, MaskingLevel.LIGHT)
            if user_agent
            else None
        )

        # Log request start
        if self.log_requests:
            self._log_request_start(request, correlation_id, session_id, masked_ip, masked_ua)

        try:
            # Process request
            response = await call_next(request)

            # Add correlation ID to response headers
            if self.include_response_header and correlation_id:
                response.headers[self.header_name] = correlation_id
                response.headers["X-Session-ID"] = session_id or "anonymous"

                # Turkish compliance headers
                response.headers["X-KVKV-Compliant"] = "true"
                response.headers["X-Data-Processing-Purpose"] = "service_provision"

            # Log successful request completion
            if self.log_requests:
                self._log_request_completion(
                    request, response, correlation_id, start_time, "success"
                )

            return response

        except Exception as e:
            # Log failed request
            if self.log_requests:
                self._log_request_completion(
                    request, None, correlation_id, start_time, "error", str(e)
                )

            # Re-raise exception for proper error handling
            raise

        finally:
            # Clear context variables
            correlation_id_ctx.set(None)
            session_id_ctx.set(None)
            request_id_ctx.set(None)
            request_start_time_ctx.set(None)

    def _extract_correlation_id(self, request: Request) -> str:
        """Extract or generate correlation ID from request.

        Args:
            request: HTTP request

        Returns:
            Correlation ID string
        """
        # Try to get from headers (case-insensitive)
        correlation_id = request.headers.get(self.header_name.lower())

        # Try alternative header names
        if not correlation_id:
            alt_headers = ["x-request-id", "x-trace-id", "request-id", "trace-id"]
            for header in alt_headers:
                correlation_id = request.headers.get(header)
                if correlation_id:
                    break

        # Generate new UUID if missing and generation is enabled
        if not correlation_id and self.generate_if_missing:
            correlation_id = str(uuid.uuid4())

        return correlation_id or "unknown"

    def _extract_session_id(self, request: Request) -> Optional[str]:
        """Extract session ID from request cookies or headers.

        Args:
            request: HTTP request

        Returns:
            Session ID if found, None otherwise
        """
        # Try session cookie first
        session_id = request.cookies.get("session_id")

        # Try authorization header (extract from JWT if present)
        if not session_id:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                # Extract session info from JWT (implementation depends on JWT structure)
                session_id = self._extract_session_from_jwt(auth_header[7:])

        # Try X-Session-ID header
        if not session_id:
            session_id = request.headers.get("x-session-id")

        return session_id

    def _extract_session_from_jwt(self, jwt_token: str) -> Optional[str]:
        """Extract session ID from JWT token.

        Args:
            jwt_token: JWT token string

        Returns:
            Session ID if extractable, None otherwise
        """
        try:
            # Basic JWT parsing without verification (for session ID only)
            import json
            import base64

            # Split JWT into parts
            parts = jwt_token.split(".")
            if len(parts) != 3:
                return None

            # Decode payload (add padding if needed)
            payload_b64 = parts[1]
            padding = 4 - (len(payload_b64) % 4)
            if padding != 4:
                payload_b64 += "=" * padding

            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            payload = json.loads(payload_bytes)

            # Extract session ID from JWT claims
            return payload.get("session_id") or payload.get("sid")

        except Exception:
            # JWT parsing failed - not critical for correlation
            return None

    def _extract_client_ip(self, request: Request) -> Optional[str]:
        """Extract client IP address with proxy support.

        Args:
            request: HTTP request

        Returns:
            Client IP address
        """
        # Check for forwarded headers (load balancer/proxy)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Take first IP in chain (original client)
            return forwarded_for.split(",")[0].strip()

        # Check for real IP header
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip

        # Fallback to direct connection IP
        if hasattr(request, "client") and request.client:
            return request.client.host

        return None

    def _log_request_start(
        self,
        request: Request,
        correlation_id: str,
        session_id: Optional[str],
        masked_ip: Optional[str],
        masked_ua: Optional[str],
    ) -> None:
        """Log request start with correlation tracking.

        Args:
            request: HTTP request
            correlation_id: Request correlation ID
            session_id: Session ID if available
            masked_ip: KVKV-compliant masked IP address
            masked_ua: KVKV-compliant masked user agent
        """
        # Prepare request headers for logging (mask sensitive ones)
        headers_to_log = {}

        if self.mask_sensitive_headers:
            sensitive_headers = {
                "authorization",
                "cookie",
                "x-api-key",
                "x-auth-token",
                "authentication",
                "proxy-authorization",
            }

            for name, value in request.headers.items():
                if name.lower() in sensitive_headers:
                    headers_to_log[name] = "***MASKED***"
                else:
                    headers_to_log[name] = value
        else:
            headers_to_log = dict(request.headers)

        logger.info(
            "request_started",
            correlation_id=correlation_id,
            session_id=session_id,
            method=request.method,
            path=str(request.url.path),
            query_params=str(request.url.query) if request.url.query else None,
            ip_masked=masked_ip,
            ua_masked=masked_ua,
            headers=headers_to_log if headers_to_log else None,
            content_type=request.headers.get("content-type"),
            content_length=request.headers.get("content-length"),
            host=request.headers.get("host"),
            referer=request.headers.get("referer"),
            event_type="request_start",
            compliance="KVKV_GDPR",
        )

    def _log_request_completion(
        self,
        request: Request,
        response: Optional[Response],
        correlation_id: str,
        start_time: float,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Log request completion with timing and correlation.

        Args:
            request: HTTP request
            response: HTTP response (None if error)
            correlation_id: Request correlation ID
            start_time: Request start timestamp
            status: Request status (success/error)
            error_message: Error message if status is error
        """
        import time

        duration_ms = int((time.time() - start_time) * 1000)

        log_data = {
            "event_type": "request_completed",
            "correlation_id": correlation_id,
            "method": request.method,
            "path": str(request.url.path),
            "status": status,
            "duration_ms": duration_ms,
            "compliance": "KVKV_GDPR",
        }

        if response:
            log_data["status_code"] = response.status_code
            log_data["response_size"] = response.headers.get("content-length")

        if error_message:
            log_data["error"] = error_message

        # Log as warning if slow request (>2s) or error
        if duration_ms > 2000:
            logger.warning("slow_request_detected", **log_data)
        elif status == "error":
            logger.error("request_failed", **log_data)
        else:
            logger.info("request_completed", **log_data)


def get_correlation_id() -> Optional[str]:
    """Get current request correlation ID from context.

    Returns:
        Current correlation ID or None if not set
    """
    return correlation_id_ctx.get()


def get_session_id() -> Optional[str]:
    """Get current session ID from context.

    Returns:
        Current session ID or None if not set
    """
    return session_id_ctx.get()


def get_request_start_time() -> Optional[float]:
    """Get current request start time from context.

    Returns:
        Request start timestamp or None if not set
    """
    return request_start_time_ctx.get()


# Export main components
__all__ = [
    "CorrelationMiddleware",
    "correlation_id_ctx",
    "session_id_ctx",
    "get_correlation_id",
    "get_session_id",
    "get_request_start_time",
]
