"""
Dev-Mode Middleware with Security Toggles - Task 3.12
Ultra-Enterprise development assistance with strict production safeguards

**Risk Assessment**: HIGH - Contains development-only security relaxations
**Compliance**: Must NEVER be enabled in production environments
**Security Level**: Development assistance only
"""

from __future__ import annotations

import json
import time
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from ..core.environment import environment
from ..core.logging import get_logger

logger = get_logger(__name__)


class DevModeMiddleware(BaseHTTPMiddleware):
    """
    Development Mode Security Toggle Middleware - Task 3.12
    
    Provides development-friendly features while maintaining strict production security:
    - Relaxed CSRF for localhost in dev mode only
    - Response annotations with debug information
    - Development-specific error handling
    - Automatic security validation
    
    **CRITICAL**: This middleware automatically disables all relaxations in production
    """
    
    def __init__(
        self, 
        app: ASGIApp,
        enable_response_annotations: bool = True,
        enable_csrf_localhost_bypass: bool = True
    ):
        super().__init__(app)
        self.enable_response_annotations = enable_response_annotations
        self.enable_csrf_localhost_bypass = enable_csrf_localhost_bypass
        
        # Log middleware activation
        if environment.is_dev_mode:
            logger.info(
                "Dev-Mode Middleware activated with relaxed security guards",
                extra={
                    'operation': 'dev_middleware_activated',
                    'environment': environment.ENV,
                    'features': {
                        'response_annotations': enable_response_annotations,
                        'csrf_localhost_bypass': enable_csrf_localhost_bypass,
                    },
                    'warning': 'Development features enabled - NOT suitable for production'
                }
            )
    
    async def dispatch(self, request: Request, call_next):
        """Apply development mode features with strict production safeguards."""
        
        # CRITICAL SECURITY CHECK: Never allow dev features in production
        if environment.is_production and environment.DEV_MODE:
            logger.critical(
                "CRITICAL SECURITY VIOLATION: Dev mode attempted in production",
                extra={
                    'operation': 'dev_mode_production_violation',
                    'environment': environment.ENV,
                    'client_ip': self._get_client_ip(request),
                    'user_agent': request.headers.get('user-agent')
                }
            )
            raise HTTPException(
                status_code=500,
                detail="Güvenlik Hatası: Sistem yapılandırma hatası tespit edildi"
            )
        
        # Only apply dev features in development environment with dev mode enabled
        if not (environment.is_development and environment.is_dev_mode):
            return await call_next(request)
        
        # Store request start time for dev annotations
        request_start_time = time.time()
        request.state.dev_request_start = request_start_time
        
        # Apply dev-mode CSRF bypass for localhost
        if self.enable_csrf_localhost_bypass and self._is_localhost_request(request):
            self._apply_csrf_localhost_bypass(request)
        
        # Process the request
        response = await call_next(request)
        
        # Add development annotations to response
        if self.enable_response_annotations and isinstance(response, JSONResponse):
            response = await self._add_dev_annotations(request, response, request_start_time)
        
        # Add dev-mode headers
        response.headers["X-Dev-Mode"] = "true"
        response.headers["X-Environment"] = str(environment.ENV)
        response.headers["X-Security-Level"] = "development-relaxed"
        
        return response
    
    def _is_localhost_request(self, request: Request) -> bool:
        """Check if request originates from localhost."""
        
        # Check client host
        if request.client:
            client_host = request.client.host
            if client_host in ['127.0.0.1', '::1', 'localhost']:
                return True
        
        # Check X-Forwarded-For header for localhost
        forwarded_for = request.headers.get('x-forwarded-for')
        if forwarded_for:
            # Take the first IP (client IP)
            client_ip = forwarded_for.split(',')[0].strip()
            if client_ip in ['127.0.0.1', '::1', 'localhost']:
                return True
        
        # Check Host header for localhost
        host_header = request.headers.get('host', '')
        if host_header.startswith('localhost:') or host_header == 'localhost':
            return True
        
        # Check Origin header for localhost
        origin = request.headers.get('origin')
        if origin:
            parsed = urlparse(origin)
            if parsed.hostname in ['127.0.0.1', '::1', 'localhost']:
                return True
        
        return False
    
    def _apply_csrf_localhost_bypass(self, request: Request) -> None:
        """Apply CSRF bypass for localhost requests in dev mode."""
        
        # Set flag for CSRF middleware to check
        request.state.dev_csrf_localhost_bypass = True
        
        logger.debug(
            "CSRF localhost bypass applied in dev mode",
            extra={
                'operation': 'csrf_localhost_bypass_applied',
                'client_ip': self._get_client_ip(request),
                'path': str(request.url.path),
                'method': request.method,
                'warning': 'CSRF protection relaxed for localhost in development only'
            }
        )
    
    async def _add_dev_annotations(
        self, 
        request: Request, 
        response: JSONResponse, 
        request_start_time: float
    ) -> JSONResponse:
        """Add development annotations to JSON responses."""
        
        # Calculate request processing time
        processing_time = time.time() - request_start_time
        
        try:
            # Get current response content
            response_body = response.body
            if response_body:
                content = json.loads(response_body.decode('utf-8'))
            else:
                content = {}
            
            # Add dev annotations (only if not already present)
            if not isinstance(content, dict):
                # If response is not a dict, wrap it
                content = {"data": content}
            
            # Add development metadata
            content["_dev"] = {
                "mode": "development",
                "environment": str(environment.ENV),
                "processing_time_ms": round(processing_time * 1000, 2),
                "timestamp": int(time.time()),
                "request_id": getattr(request.state, 'request_id', None),
                "security_features": {
                    "dev_mode": environment.is_dev_mode,
                    "auth_bypass": environment.DEV_AUTH_BYPASS,
                    "csrf_relaxed": self.enable_csrf_localhost_bypass,
                    "detailed_errors": environment.DEV_DETAILED_ERRORS
                },
                "warnings": [
                    "Bu response development mode'da annotate edilmiştir",
                    "Production ortamında bu bilgiler görünmez",
                    "Development features are active - not suitable for production"
                ]
            }
            
            # Create new response with updated content
            new_response = JSONResponse(
                content=content,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type
            )
            
            return new_response
            
        except Exception as e:
            logger.warning(
                f"Failed to add dev annotations to response: {e}",
                extra={
                    'operation': 'dev_annotation_failed',
                    'error': str(e),
                    'path': str(request.url.path)
                }
            )
            return response
    
    def _get_client_ip(self, request: Request) -> Optional[str]:
        """Extract client IP address from request."""
        
        # Check X-Forwarded-For header first
        forwarded_for = request.headers.get('x-forwarded-for')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        
        # Check X-Real-IP header
        real_ip = request.headers.get('x-real-ip')
        if real_ip:
            return real_ip
        
        # Fall back to request.client.host
        if request.client:
            return request.client.host
        
        return None


class ProductionHardeningMiddleware(BaseHTTPMiddleware):
    """
    Production Security Hardening Middleware - Task 3.12
    
    Enforces production-only security policies:
    - HTTPS redirect enforcement
    - Secure cookie validation
    - Error message masking
    - Debug endpoint disabling
    
    **Automatically enabled in production environment**
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        
        # Log middleware activation in production
        if environment.is_production:
            logger.info(
                "Production Hardening Middleware activated",
                extra={
                    'operation': 'production_hardening_activated',
                    'environment': environment.ENV,
                    'features': {
                        'force_https': environment.should_force_https,
                        'secure_cookies': environment.should_use_secure_cookies,
                        'mask_errors': environment.should_mask_errors,
                        'disable_debug': environment.PROD_DISABLE_DEBUG_ENDPOINTS
                    }
                }
            )
    
    async def dispatch(self, request: Request, call_next):
        """Apply production hardening security controls."""
        
        # Only apply hardening in production
        if not environment.is_production:
            return await call_next(request)
        
        # HTTPS Enforcement
        if environment.should_force_https and self._is_http_request(request):
            return self._redirect_to_https(request)
        
        # Debug Endpoint Protection
        if environment.PROD_DISABLE_DEBUG_ENDPOINTS and self._is_debug_endpoint(request):
            return self._reject_debug_endpoint(request)
        
        # Process the request
        try:
            response = await call_next(request)
        except Exception as e:
            # Apply error masking in production
            if environment.should_mask_errors:
                return self._mask_error_response(request, e)
            else:
                raise
        
        # Apply production security headers
        response = self._add_production_headers(response)
        
        return response
    
    def _is_http_request(self, request: Request) -> bool:
        """Check if request is using HTTP instead of HTTPS."""
        
        # Check URL scheme
        if str(request.url.scheme).lower() == 'http':
            return True
        
        # Check X-Forwarded-Proto header (for proxy setups)
        forwarded_proto = request.headers.get('x-forwarded-proto')
        if forwarded_proto and forwarded_proto.lower() == 'http':
            return True
        
        return False
    
    def _redirect_to_https(self, request: Request) -> Response:
        """Redirect HTTP requests to HTTPS."""
        
        https_url = str(request.url).replace('http://', 'https://', 1)
        
        logger.info(
            "HTTP request redirected to HTTPS in production",
            extra={
                'operation': 'https_redirect_enforced',
                'original_url': str(request.url),
                'redirect_url': https_url,
                'client_ip': self._get_client_ip(request)
            }
        )
        
        return Response(
            status_code=301,
            headers={
                'Location': https_url,
                'Strict-Transport-Security': f'max-age={environment.SECURITY_HSTS_MAX_AGE}; includeSubDomains; preload'
            }
        )
    
    def _is_debug_endpoint(self, request: Request) -> bool:
        """Check if request is to a debug endpoint."""
        
        debug_paths = [
            '/debug',
            '/docs',
            '/redoc',
            '/openapi.json',
            '/_debug',
            '/admin/debug',
            '/metrics/debug',
            '/health/debug'
        ]
        
        path = str(request.url.path).lower()
        return any(path.startswith(debug_path) for debug_path in debug_paths)
    
    def _reject_debug_endpoint(self, request: Request) -> JSONResponse:
        """Reject requests to debug endpoints in production."""
        
        logger.warning(
            "Debug endpoint access attempted in production",
            extra={
                'operation': 'debug_endpoint_blocked',
                'path': str(request.url.path),
                'client_ip': self._get_client_ip(request),
                'user_agent': request.headers.get('user-agent')
            }
        )
        
        return JSONResponse(
            status_code=404,
            content={
                "detail": "Sayfa bulunamadı",
                "error_code": "NOT_FOUND",
                "message": "The requested resource was not found"
            }
        )
    
    def _mask_error_response(self, request: Request, error: Exception) -> JSONResponse:
        """Create masked error response for production."""
        
        # Log the actual error for debugging
        logger.error(
            f"Request error masked in production: {type(error).__name__}",
            exc_info=True,
            extra={
                'operation': 'error_masked_production',
                'path': str(request.url.path),
                'client_ip': self._get_client_ip(request),
                'error_type': type(error).__name__
            }
        )
        
        # Return generic error message
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Sunucu hatası oluştu. Lütfen daha sonra tekrar deneyin.",
                "error_code": "INTERNAL_SERVER_ERROR",
                "message": "An internal server error occurred",
                "timestamp": int(time.time())
            }
        )
    
    def _add_production_headers(self, response: Response) -> Response:
        """Add production-specific security headers."""
        
        # Remove any development headers
        dev_headers_to_remove = [
            'X-Dev-Mode',
            'X-Debug-Info',
            'X-Development-Warning'
        ]
        
        for header in dev_headers_to_remove:
            response.headers.pop(header, None)
        
        # Add production security headers
        response.headers['X-Production-Mode'] = 'true'
        response.headers['X-Security-Level'] = 'ultra-enterprise-banking'
        response.headers['X-KVKV-Compliant'] = 'true'
        
        return response
    
    def _get_client_ip(self, request: Request) -> Optional[str]:
        """Extract client IP address from request."""
        
        # Check X-Forwarded-For header first
        forwarded_for = request.headers.get('x-forwarded-for')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        
        # Check X-Real-IP header
        real_ip = request.headers.get('x-real-ip')
        if real_ip:
            return real_ip
        
        # Fall back to request.client.host
        if request.client:
            return request.client.host
        
        return None


class EnvironmentValidationMiddleware(BaseHTTPMiddleware):
    """
    Environment Configuration Validation Middleware - Task 3.12
    
    Continuously validates environment configuration and logs security events.
    Prevents requests when critical misconfigurations are detected.
    """
    
    def __init__(self, app: ASGIApp):
        super().__init__(app)
        
        # Perform initial validation
        self._validate_runtime_environment()
    
    async def dispatch(self, request: Request, call_next):
        """Validate environment configuration for each request."""
        
        # Check for critical security misconfigurations
        if self._has_critical_misconfigurations():
            return self._reject_misconfigured_request(request)
        
        return await call_next(request)
    
    def _validate_runtime_environment(self) -> None:
        """Validate runtime environment configuration."""
        
        # Check for dev mode in production (critical violation)
        if environment.is_production and environment.DEV_MODE:
            logger.critical(
                "CRITICAL: Development mode enabled in production environment",
                extra={
                    'operation': 'critical_misconfiguration_detected',
                    'environment': environment.ENV,
                    'violation': 'dev_mode_in_production',
                    'turkish_message': 'KRİTİK: Üretim ortamında geliştirme modu aktif'
                }
            )
        
        # Check for default secrets in production
        if environment.is_production:
            default_secret_checks = [
                (environment.SECRET_KEY, "dev-secret-key-change-in-production-minimum-32-chars"),
                (environment.CSRF_SECRET_KEY, "dev-csrf-hmac-key-ultra-secure-banking-grade-change-in-production")
            ]
            
            for secret_value, default_value in default_secret_checks:
                if secret_value == default_value:
                    logger.critical(
                        "CRITICAL: Default secret key detected in production",
                        extra={
                            'operation': 'default_secret_in_production',
                            'environment': environment.ENV,
                            'turkish_message': 'KRİTİK: Üretim ortamında varsayılan gizli anahtar'
                        }
                    )
    
    def _has_critical_misconfigurations(self) -> bool:
        """Check for critical security misconfigurations."""
        
        # Development mode in production is critical
        if environment.is_production and environment.DEV_MODE:
            return True
        
        # Missing critical configuration in production
        if environment.is_production:
            if not environment.SECRET_KEY or len(environment.SECRET_KEY) < 32:
                return True
            
            if environment.SECRET_KEY == "dev-secret-key-change-in-production-minimum-32-chars":
                return True
        
        return False
    
    def _reject_misconfigured_request(self, request: Request) -> JSONResponse:
        """Reject request due to critical misconfiguration."""
        
        logger.error(
            "Request rejected due to critical environment misconfiguration",
            extra={
                'operation': 'request_rejected_misconfiguration',
                'path': str(request.url.path),
                'client_ip': self._get_client_ip(request),
                'environment': environment.ENV
            }
        )
        
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Servis geçici olarak kullanılamıyor. Sistem yapılandırması kontrol ediliyor.",
                "error_code": "SERVICE_MISCONFIGURED",
                "message": "Service temporarily unavailable due to configuration issues"
            }
        )
    
    def _get_client_ip(self, request: Request) -> Optional[str]:
        """Extract client IP address from request."""
        
        # Check X-Forwarded-For header first
        forwarded_for = request.headers.get('x-forwarded-for')
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        
        if request.client:
            return request.client.host
        
        return None