from __future__ import annotations

import json

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from ..core.logging import get_logger
from ..core.security import security_manager
from ..settings import app_settings as appset

logger = get_logger(__name__)


class EnterpriseSecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Ultra enterprise security headers middleware with CSP nonce support.
    
    Implements banking-level security controls including:
    - Dynamic CSP with nonce generation
    - Ultra strict Permissions-Policy
    - Environment-aware security policies
    - XSS detection and logging
    - CSP violation reporting
    """

    def __init__(self, app, csp_report_endpoint: str = "/api/security/csp-report"):
        super().__init__(app)
        self.csp_report_endpoint = csp_report_endpoint

    async def dispatch(self, request: Request, call_next):
        """Apply ultra enterprise security headers to all responses."""

        # Generate unique nonce for this request
        nonce = security_manager.generate_csp_nonce()

        # Store nonce in request state for use in templates
        request.state.csp_nonce = nonce

        # Process the request
        response: Response = await call_next(request)

        # Apply security headers only if CSP is enabled
        if appset.security_csp_enabled:
            headers = security_manager.get_enterprise_security_headers(
                nonce=nonce,
                environment=appset.security_environment,
                hsts_enabled=appset.security_hsts_enabled
            )

            # Add CSP report URI if configured
            if appset.security_csp_report_uri:
                csp_policy = headers.get("Content-Security-Policy", "")
                if csp_policy:
                    headers["Content-Security-Policy"] = f"{csp_policy}; report-uri {appset.security_csp_report_uri}"

            # Apply all security headers
            for header_name, header_value in headers.items():
                response.headers.setdefault(header_name, header_value)

        # Apply basic security headers even if CSP is disabled
        else:
            basic_headers = {
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Referrer-Policy": "no-referrer",
                "X-XSS-Protection": "1; mode=block",
            }

            if appset.security_hsts_enabled and appset.security_environment != "development":
                basic_headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"

            for header_name, header_value in basic_headers.items():
                response.headers.setdefault(header_name, header_value)

        return response


class XSSDetectionMiddleware(BaseHTTPMiddleware):
    """Ultra enterprise XSS detection and prevention middleware.
    
    Detects and logs potential XSS attempts in request data.
    Integrates with security event logging system.
    """

    async def dispatch(self, request: Request, call_next):
        """Detect XSS attempts in request data."""

        # Skip XSS detection if disabled
        if not appset.security_xss_detection_enabled:
            return await call_next(request)

        # Extract request data for analysis
        request_data = await self._extract_request_data(request)

        # Check for suspicious patterns
        if security_manager.is_suspicious_request(request_data):
            # Log security event
            await self._log_xss_attempt(request, request_data)

            # Return security error in Turkish
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "Güvenlik: Şüpheli içerik tespit edildi. İstek reddedildi.",
                    "error_code": "XSS_ATTEMPT_DETECTED",
                    "message": "Request contains potentially malicious content"
                },
                headers={
                    "X-Content-Type-Options": "nosniff",
                    "X-Frame-Options": "DENY"
                }
            )

        return await call_next(request)

    async def _extract_request_data(self, request: Request) -> dict:
        """Extract request data for XSS analysis."""
        data = {}

        try:
            # Query parameters
            data.update(dict(request.query_params))

            # Path parameters
            if hasattr(request, 'path_params'):
                data.update(request.path_params)

            # Headers (selected safe ones)
            safe_headers = ['user-agent', 'referer', 'x-forwarded-for']
            for header in safe_headers:
                if header in request.headers:
                    data[f"header_{header}"] = request.headers[header]

            # For POST requests, read body safely without consuming it
            if request.method in ["POST", "PUT", "PATCH"]:
                content_type = request.headers.get("content-type", "")
                if "application/json" in content_type:
                    try:
                        # Read body safely
                        body = await request.body()
                        if body:
                            # Decode and parse JSON for XSS analysis
                            body_text = body.decode('utf-8')

                            # Parse JSON to extract field values for analysis
                            try:
                                body_json = json.loads(body_text)
                                if isinstance(body_json, dict):
                                    for key, value in body_json.items():
                                        data[f"body_{key}"] = str(value)[:1000]  # Limit to prevent DOS
                                else:
                                    data["body_content"] = str(body_json)[:1000]
                            except json.JSONDecodeError:
                                # Not valid JSON, analyze as plain text
                                data["body_content"] = body_text[:1000]

                            # Important: Recreate request with body for downstream handlers
                            async def receive():
                                return {"type": "http.request", "body": body}

                            # Replace request's receive method
                            request._receive = receive

                    except Exception as e:
                        logger.warning(f"Error reading request body for XSS analysis: {e}")
                elif "application/x-www-form-urlencoded" in content_type:
                    try:
                        # Handle form data
                        body = await request.body()
                        if body:
                            from urllib.parse import parse_qs
                            body_text = body.decode('utf-8')
                            form_data = parse_qs(body_text)
                            for key, values in form_data.items():
                                if values:
                                    data[f"form_{key}"] = str(values[0])[:1000]

                            # Recreate request with body
                            async def receive():
                                return {"type": "http.request", "body": body}
                            request._receive = receive

                    except Exception as e:
                        logger.warning(f"Error reading form data for XSS analysis: {e}")

        except Exception as e:
            logger.warning(f"Error extracting request data for XSS analysis: {e}")

        return data

    async def _log_xss_attempt(self, request: Request, request_data: dict):
        """Log XSS attempt as security event."""
        try:
            # Extract client information
            client_ip = request.client.host if request.client else None
            user_agent = request.headers.get("user-agent")

            logger.warning(
                "XSS attempt detected",
                extra={
                    'operation': 'xss_attempt_detected',
                    'client_ip': client_ip,
                    'user_agent': user_agent,
                    'path': str(request.url.path),
                    'method': request.method,
                    'suspicious_data': str(request_data)[:500]  # Limit size
                }
            )

        except Exception as e:
            logger.error(f"Error logging XSS attempt: {e}")


# Legacy middleware class for backward compatibility
SecurityHeadersMiddleware = EnterpriseSecurityHeadersMiddleware


class CORSMiddlewareStrict(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        origin = request.headers.get("origin")
        allowed = (not appset.cors_allowed_origins) or (origin in appset.cors_allowed_origins)
        if origin and not allowed:
            resp = Response(status_code=403, content="İstek kaynağı (Origin) izinli değil.")
            resp.headers["Vary"] = "Origin"
            return resp
        if request.method == "OPTIONS":
            resp = Response(status_code=204)
            if origin and allowed:
                resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Vary"] = "Origin"
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = request.headers.get("access-control-request-headers", "*")
            resp.headers["Access-Control-Allow-Credentials"] = "false"
            resp.headers["Access-Control-Max-Age"] = "600"
            return resp
        response: Response = await call_next(request)
        if origin and allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
        response.headers["Access-Control-Allow-Credentials"] = "false"
        return response


