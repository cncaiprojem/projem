"""
Request/Response logging middleware with correlation IDs and performance tracking.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from ulid import ULID

from ..core.logging import (
    get_logger,
    log_security_event,
    request_id_ctx,
    user_id_ctx,
)

logger = get_logger(__name__)


def generate_request_id() -> str:
    """Generate a unique request ID using ULID for sortability."""
    return str(ULID())


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Comprehensive logging middleware for FastAPI.
    
    Features:
    - Request/response logging with timing
    - Correlation ID generation and propagation
    - Request/response size tracking
    - Slow request detection
    - Security event logging
    - Turkish error messages
    """

    def __init__(
        self,
        app: ASGIApp,
        slow_request_threshold_ms: int = 1000,
        log_request_body: bool = False,
        log_response_body: bool = False,
        excluded_paths: list[str] | None = None,
    ) -> None:
        """
        Initialize logging middleware.
        
        Args:
            app: FastAPI application
            slow_request_threshold_ms: Threshold for slow request warnings (default: 1000ms)
            log_request_body: Whether to log request bodies (be careful with sensitive data)
            log_response_body: Whether to log response bodies (be careful with large responses)
            excluded_paths: Paths to exclude from logging (e.g., /health, /metrics)
        """
        super().__init__(app)
        self.slow_request_threshold_ms = slow_request_threshold_ms
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.excluded_paths = excluded_paths or ["/health", "/ready", "/metrics", "/docs", "/openapi.json"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and log details."""
        # Skip logging for excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        # Generate or extract request ID
        request_id = request.headers.get("X-Request-ID") or generate_request_id()
        request_id_ctx.set(request_id)

        # Extract user ID from request if available
        user_id = None
        if hasattr(request.state, "user"):
            user_id = getattr(request.state.user, "id", None)
            if user_id:
                user_id_ctx.set(str(user_id))

        try:
            # Start timing
            start_time = time.perf_counter()

            # Get request details
            client_host = None
            if request.client:
                client_host = request.client.host

            # Log request
            request_log_data = {
                "event": "request_started",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "query_params": dict(request.query_params) if request.query_params else None,
                "client_host": client_host,
                "user_agent": request.headers.get("User-Agent"),
                "referer": request.headers.get("Referer"),
                "content_type": request.headers.get("Content-Type"),
                "content_length": request.headers.get("Content-Length"),
            }

            if user_id:
                request_log_data["user_id"] = user_id

            # Log request body if enabled and not too large
            if self.log_request_body and request.headers.get("Content-Length"):
                try:
                    content_length = int(request.headers.get("Content-Length", 0))
                    if content_length > 0 and content_length < 10000:  # Don't log bodies > 10KB
                        # Note: This will consume the request body, need to restore it
                        body = await request.body()
                        request_log_data["request_body_size"] = len(body)
                        # Don't log the actual body to avoid sensitive data exposure
                except Exception:
                    pass

            logger.info("http_request", **request_log_data)

            # Process request
            response = None
            error_occurred = False
            error_message = None

            try:
                response = await call_next(request)
            except Exception as e:
                error_occurred = True
                error_message = str(e)

                # Log error
                elapsed_ms = int((time.perf_counter() - start_time) * 1000)
                logger.error(
                    "http_request_error",
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    error=error_message,
                    error_type=type(e).__name__,
                    elapsed_ms=elapsed_ms,
                    exc_info=True,
                )

                # Log security event for suspicious errors
                if "unauthorized" in error_message.lower() or "forbidden" in error_message.lower():
                    log_security_event(
                        "unauthorized_access_attempt",
                        user_id=user_id,
                        ip_address=client_host,
                        details={
                            "path": request.url.path,
                            "method": request.method,
                            "error": error_message,
                        }
                    )

                raise

            # Calculate elapsed time
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)

            # Add correlation ID to response headers
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{elapsed_ms}ms"

            # Log response
            response_log_data = {
                "event": "request_completed",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "elapsed_ms": elapsed_ms,
            }

            if user_id:
                response_log_data["user_id"] = user_id

            # Add response size if available
            if "Content-Length" in response.headers:
                response_log_data["response_size"] = response.headers["Content-Length"]

            # Determine log level based on status code and elapsed time
            if response.status_code >= 500:
                # Server errors
                logger.error("http_response_error", **response_log_data)

                # Log critical security events
                if response.status_code == 500:
                    log_security_event(
                        "internal_server_error",
                        user_id=user_id,
                        ip_address=client_host,
                        details={
                            "path": request.url.path,
                            "method": request.method,
                        }
                    )
            elif response.status_code >= 400:
                # Client errors
                if response.status_code == 401:
                    log_security_event(
                        "authentication_failed",
                        user_id=user_id,
                        ip_address=client_host,
                        details={
                            "path": request.url.path,
                            "method": request.method,
                        }
                    )
                elif response.status_code == 403:
                    log_security_event(
                        "authorization_failed",
                        user_id=user_id,
                        ip_address=client_host,
                        details={
                            "path": request.url.path,
                            "method": request.method,
                        }
                    )
                elif response.status_code == 429:
                    log_security_event(
                        "rate_limit_exceeded",
                        user_id=user_id,
                        ip_address=client_host,
                        details={
                            "path": request.url.path,
                            "method": request.method,
                        }
                    )

                logger.warning("http_response_client_error", **response_log_data)
            elif elapsed_ms > self.slow_request_threshold_ms:
                # Slow requests
                response_log_data["event"] = "slow_request"
                logger.warning("http_response_slow", **response_log_data)
            else:
                # Success
                logger.info("http_response", **response_log_data)

            return response

        finally:
            # Clear context variables regardless of success/failure
            request_id_ctx.set(None)
            user_id_ctx.set(None)


class CorrelationIdMiddleware:
    """
    ASGI middleware for correlation ID management.
    This is a lighter alternative to LoggingMiddleware if you only need correlation IDs.
    """

    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID") -> None:
        """
        Initialize correlation ID middleware.
        
        Args:
            app: ASGI application
            header_name: Header name for correlation ID
        """
        self.app = app
        self.header_name = header_name.lower().encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract or generate correlation ID
        request_id = None
        for header_name, header_value in scope["headers"]:
            if header_name == self.header_name:
                request_id = header_value.decode()
                break

        if not request_id:
            request_id = generate_request_id()

        # Set context variable
        request_id_ctx.set(request_id)

        async def send_wrapper(message: Message) -> None:
            """Add correlation ID to response headers."""
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((self.header_name, request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # Clear context variable
            request_id_ctx.set(None)


class PerformanceLoggingMiddleware:
    """
    ASGI middleware for detailed performance logging.
    Tracks timing for different phases of request processing.
    """

    def __init__(self, app: ASGIApp, slow_threshold_ms: int = 1000) -> None:
        """
        Initialize performance logging middleware.
        
        Args:
            app: ASGI application
            slow_threshold_ms: Threshold for slow request warnings
        """
        self.app = app
        self.slow_threshold_ms = slow_threshold_ms
        self.logger = get_logger(__name__)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process ASGI request with performance tracking."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Start timing
        start_time = time.perf_counter()
        first_byte_time = None

        # Extract request details
        path = scope.get("path", "")
        method = scope.get("method", "")

        async def send_wrapper(message: Message) -> None:
            """Track first byte timing."""
            nonlocal first_byte_time

            if message["type"] == "http.response.start" and first_byte_time is None:
                first_byte_time = time.perf_counter()
                time_to_first_byte = int((first_byte_time - start_time) * 1000)

                if time_to_first_byte > self.slow_threshold_ms:
                    self.logger.warning(
                        "slow_time_to_first_byte",
                        path=path,
                        method=method,
                        ttfb_ms=time_to_first_byte,
                    )

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            # Log total request time
            total_time = int((time.perf_counter() - start_time) * 1000)

            if total_time > self.slow_threshold_ms:
                self.logger.warning(
                    "slow_request_total",
                    path=path,
                    method=method,
                    total_ms=total_time,
                    ttfb_ms=int((first_byte_time - start_time) * 1000) if first_byte_time else None,
                )


def setup_request_logging(
    app: ASGIApp,
    use_correlation_ids: bool = True,
    use_performance_logging: bool = True,
    slow_request_threshold_ms: int = 1000,
    excluded_paths: list[str] | None = None,
) -> ASGIApp:
    """
    Set up all logging middleware for an ASGI application.
    
    Args:
        app: ASGI application
        use_correlation_ids: Whether to use correlation ID middleware
        use_performance_logging: Whether to use performance logging middleware
        slow_request_threshold_ms: Threshold for slow request warnings
        excluded_paths: Paths to exclude from logging
    
    Returns:
        ASGI application with logging middleware
    """
    # Add middleware in reverse order (last added is executed first)
    if use_performance_logging:
        app = PerformanceLoggingMiddleware(app, slow_threshold_ms=slow_request_threshold_ms)

    if use_correlation_ids:
        app = CorrelationIdMiddleware(app)

    # Main logging middleware is added through FastAPI's add_middleware

    return app
