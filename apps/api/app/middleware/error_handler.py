"""
Error Handler Middleware for Task 7.12

This middleware provides:
- Global exception handling for all requests
- Error response formatting
- PII masking in logs
- Correlation ID tracking
- Metrics collection for errors
- Integration with error taxonomy
"""

from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, Optional

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..core.exceptions import (
    EnterpriseException,
    ErrorCode,
    ErrorResponse,
    FreeCADException,
    ValidationException,
    StorageException,
    AIException,
    map_exception_to_error_response,
    log_error_with_masking,
)
from ..core.pii import PIIMasker
from ..core.logging import get_logger
from ..core import metrics
from ..middleware.correlation_middleware import get_correlation_id
from ..core.telemetry import create_span

logger = get_logger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Middleware for handling all exceptions and formatting error responses."""
    
    def __init__(self, app: FastAPI):
        super().__init__(app)
        self.error_counts: Dict[str, int] = {}
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and handle any exceptions."""
        
        start_time = time.time()
        correlation_id = get_correlation_id()
        
        try:
            # Process request
            response = await call_next(request)
            
            # Check for error status codes
            if response.status_code >= 400:
                duration_ms = (time.time() - start_time) * 1000
                
                # Log error response
                log_error_with_masking(
                    logger,
                    "Request failed with error status",
                    path=str(request.url.path),
                    method=request.method,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    correlation_id=correlation_id
                )
                
                # Update metrics with normalized path
                normalized_path = self._normalize_path(str(request.url.path))
                metrics.http_requests_total.labels(
                    method=request.method,
                    endpoint=normalized_path,
                    status=response.status_code
                ).inc()
                
                metrics.http_request_duration_seconds.labels(
                    method=request.method,
                    endpoint=normalized_path
                ).observe(duration_ms / 1000)
            
            return response
            
        except EnterpriseException as e:
            # Handle our custom exceptions
            return await self._handle_enterprise_exception(
                request, e, start_time, correlation_id
            )
            
        except Exception as e:
            # Handle unexpected exceptions
            return await self._handle_unexpected_exception(
                request, e, start_time, correlation_id
            )
    
    async def _handle_enterprise_exception(
        self,
        request: Request,
        exception: EnterpriseException,
        start_time: float,
        correlation_id: str
    ) -> JSONResponse:
        """Handle EnterpriseException and return formatted response."""
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Get error response
        error_response = exception.to_error_response()
        
        # Log with masking
        log_error_with_masking(
            logger,
            "Enterprise exception occurred",
            exception=exception,
            path=str(request.url.path),
            method=request.method,
            error_code=error_response.code.value,
            http_status=error_response.http_status,
            duration_ms=duration_ms,
            job_id=error_response.job_id,
            phase=exception.phase,
            correlation_id=correlation_id
        )
        
        # Update metrics
        self._update_error_metrics(
            request,
            error_response.code,
            error_response.http_status,
            duration_ms
        )
        
        # Create telemetry span
        with create_span("error_handler", correlation_id=correlation_id) as span:
            span.set_attribute("error.code", error_response.code.value)
            span.set_attribute("error.http_status", error_response.http_status)
            span.set_attribute("error.category", self._get_error_category(error_response.code))
            span.set_attribute("request.path", str(request.url.path))
            span.set_attribute("request.method", request.method)
            
            if error_response.job_id:
                span.set_attribute("job.id", error_response.job_id)
        
        # Return JSON response
        return JSONResponse(
            status_code=error_response.http_status,
            content=error_response.dict(),
            headers={
                "X-Request-ID": correlation_id,
                "X-Error-Code": error_response.code.value,
            }
        )
    
    async def _handle_unexpected_exception(
        self,
        request: Request,
        exception: Exception,
        start_time: float,
        correlation_id: str
    ) -> JSONResponse:
        """Handle unexpected exceptions and return formatted response."""
        
        duration_ms = (time.time() - start_time) * 1000
        
        # Try to extract job_id from request context
        job_id = None
        if hasattr(request.state, "job_id"):
            job_id = request.state.job_id
        
        # Map exception to error response
        error_response = map_exception_to_error_response(
            exception,
            job_id=job_id,
            phase="request_processing"
        )
        
        # Log with masking
        log_error_with_masking(
            logger,
            "Unexpected exception occurred",
            exception=exception,
            path=str(request.url.path),
            method=request.method,
            error_code=error_response.code.value,
            http_status=error_response.http_status,
            duration_ms=duration_ms,
            correlation_id=correlation_id
        )
        
        # Update metrics
        self._update_error_metrics(
            request,
            error_response.code,
            error_response.http_status,
            duration_ms
        )
        
        # Create telemetry span
        with create_span("unexpected_error_handler", correlation_id=correlation_id) as span:
            span.set_attribute("error.code", error_response.code.value)
            span.set_attribute("error.http_status", error_response.http_status)
            span.set_attribute("error.unexpected", True)
            span.set_attribute("request.path", str(request.url.path))
            span.set_attribute("request.method", request.method)
        
        # Return JSON response
        return JSONResponse(
            status_code=error_response.http_status,
            content=error_response.dict(),
            headers={
                "X-Request-ID": correlation_id,
                "X-Error-Code": error_response.code.value,
            }
        )
    
    def _update_error_metrics(
        self,
        request: Request,
        error_code: ErrorCode,
        http_status: int,
        duration_ms: float
    ) -> None:
        """Update error-related metrics."""
        
        # HTTP metrics
        metrics.http_requests_total.labels(
            method=request.method,
            endpoint=self._normalize_path(str(request.url.path)),
            status=http_status
        ).inc()
        
        metrics.http_request_duration_seconds.labels(
            method=request.method,
            endpoint=self._normalize_path(str(request.url.path))
        ).observe(duration_ms / 1000)
        
        # Error metrics
        error_category = self._get_error_category(error_code)
        
        metrics.error_count_total.labels(
            error_code=error_code.value,
            category=error_category,
            http_status=http_status
        ).inc()
        
        # Track error rate per endpoint with normalized path
        normalized_path = self._normalize_path(str(request.url.path))
        endpoint_key = f"{request.method}:{normalized_path}"
        self.error_counts[endpoint_key] = self.error_counts.get(endpoint_key, 0) + 1
    
    def _normalize_path(self, path: str) -> str:
        """Normalize path by replacing dynamic segments with placeholders.
        
        This prevents sensitive information in path parameters from being
        exposed in metrics and logs.
        
        Examples:
            /users/123 -> /users/{id}
            /jobs/abc-def-123 -> /jobs/{id}
            /queues/my_queue/pause -> /queues/{name}/pause
        """
        
        # Common patterns for dynamic segments
        # IMPORTANT: Order matters! Specific patterns must come before generic ones
        patterns = [
            # Specific path patterns (must come first)
            # Use capture groups properly to handle paths with or without trailing slash
            (r'(/queues/)[^/]+', r'\1{name}'),
            (r'(/users/)[^/]+', r'\1{username}'),
            (r'(/projects/)[^/]+', r'\1{name}'),
            (r'(/artefacts/)[^/]+', r'\1{id}'),
            (r'(/jobs/)[^/]+', r'\1{id}'),
            # UUIDs (more specific than alphanumeric)
            (r'/([a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})(?=/|$)', '/{id}'),
            # Numeric IDs (more specific than alphanumeric)
            (r'/(\d+)(?=/|$)', '/{id}'),
            # Generic alphanumeric IDs (must come last as it's the most generic)
            # Match IDs that are at least 12 chars (typical for job IDs, file IDs, etc.)
            # This avoids matching common action names like 'download', 'upload', 'status', etc.
            (r'/([a-zA-Z0-9_-]{12,})(?=/|$)', '/{id}'),
        ]
        
        normalized = path
        for pattern, replacement in patterns:
            normalized = re.sub(pattern, replacement, normalized)
        
        return normalized
    
    def _get_error_category(self, error_code: ErrorCode) -> str:
        """Get error category from error code using dictionary lookup."""
        
        # Dictionary mapping prefixes to categories for cleaner code
        category_map = {
            "AI_": "ai",
            "VALIDATION_": "validation",
            "FC_": "freecad",
            "STORAGE_": "storage",
            "AUTH_": "auth",
        }
        
        # Special cases
        special_cases = {
            "RATE_LIMITED": "rate_limit",
            "TIMEOUT_WORKER": "system",
            "MEMORY_LIMIT_EXCEEDED": "system",
            "CPU_LIMIT_EXCEEDED": "system",
        }
        
        code_str = error_code.value
        
        # Check special cases first
        if code_str in special_cases:
            return special_cases[code_str]
        
        # Check prefixes
        for prefix, category in category_map.items():
            if code_str.startswith(prefix):
                return category
        
        return "unknown"


def create_exception_handler_factory(
    log_message: str,
    component: Optional[str] = None
) -> Callable:
    """
    Factory function to create exception handlers with reduced duplication.
    
    Args:
        log_message: Message to log when the exception occurs
        component: Optional component name for the error context
    
    Returns:
        An async exception handler function
    """
    async def exception_handler(request: Request, exc: EnterpriseException):
        """Generic exception handler created by factory."""
        
        error_response = exc.to_error_response()
        
        # Build log kwargs
        log_kwargs = {
            "exception": exc,
            "path": str(request.url.path),
            "method": request.method,
            "error_code": error_response.code.value,
        }
        
        if component:
            log_kwargs["component"] = component
        
        # Log error
        log_error_with_masking(logger, log_message, **log_kwargs)
        
        # Build response headers
        headers = {
            "X-Request-ID": error_response.request_id or "",
            "X-Error-Code": error_response.code.value,
        }
        
        if component:
            headers["X-Component"] = component
        
        return JSONResponse(
            status_code=error_response.http_status,
            content=error_response.dict(),
            headers=headers
        )
    
    return exception_handler


def create_error_handlers(app: FastAPI) -> None:
    """Create FastAPI exception handlers for specific exception types."""
    
    # Use factory to create handlers with minimal duplication
    app.add_exception_handler(
        EnterpriseException,
        create_exception_handler_factory("Handled enterprise exception")
    )
    
    app.add_exception_handler(
        FreeCADException,
        create_exception_handler_factory("FreeCAD operation failed", "freecad")
    )
    
    app.add_exception_handler(
        ValidationException,
        create_exception_handler_factory("Validation failed", "validation")
    )
    
    app.add_exception_handler(
        StorageException,
        create_exception_handler_factory("Storage operation failed", "storage")
    )
    
    app.add_exception_handler(
        AIException,
        create_exception_handler_factory("AI processing failed", "ai")
    )
    
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        """Handle ValueError as validation error."""
        
        validation_exc = ValidationException(
            message=str(exc),
            details={"original_exception": "ValueError"}
        )
        
        # Use the factory-created handler
        handler = create_exception_handler_factory("Validation failed", "validation")
        return await handler(request, validation_exc)
    
    @app.exception_handler(TimeoutError)
    async def timeout_error_handler(request: Request, exc: TimeoutError):
        """Handle TimeoutError."""
        
        error_response = ErrorResponse(
            code=ErrorCode.TIMEOUT_WORKER,
            http_status=status.HTTP_504_GATEWAY_TIMEOUT,
            message_en="Operation timed out",
            message_tr="İşlem zaman aşımına uğradı",
            request_id=get_correlation_id()
        )
        
        log_error_with_masking(
            logger,
            "Request timed out",
            exception=exc,
            path=str(request.url.path),
            method=request.method
        )
        
        return JSONResponse(
            status_code=error_response.http_status,
            content=error_response.dict(),
            headers={
                "X-Request-ID": error_response.request_id or "",
                "X-Error-Code": error_response.code.value,
            }
        )
    
    @app.exception_handler(MemoryError)
    async def memory_error_handler(request: Request, exc: MemoryError):
        """Handle MemoryError."""
        
        error_response = ErrorResponse(
            code=ErrorCode.MEMORY_LIMIT_EXCEEDED,
            http_status=status.HTTP_507_INSUFFICIENT_STORAGE,
            message_en="Memory limit exceeded",
            message_tr="Bellek sınırı aşıldı",
            request_id=get_correlation_id()
        )
        
        log_error_with_masking(
            logger,
            "Memory limit exceeded",
            exception=exc,
            path=str(request.url.path),
            method=request.method
        )
        
        return JSONResponse(
            status_code=error_response.http_status,
            content=error_response.dict(),
            headers={
                "X-Request-ID": error_response.request_id or "",
                "X-Error-Code": error_response.code.value,
            }
        )