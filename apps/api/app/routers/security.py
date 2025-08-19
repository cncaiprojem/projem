"""
Ultra enterprise security endpoints for FreeCAD CNC/CAM platform.
Handles CSP violation reporting and security event management.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..core.logging import get_logger
from ..db import get_db
from ..models.security_event import SecurityEvent
from ..services.input_sanitization_service import input_sanitization_service

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/security",
    tags=["security"],
    responses={
        403: {"description": "Güvenlik ihlali - erişim reddedildi"},
        429: {"description": "Çok fazla istek - rate limit aşıldı"}
    }
)


class CSPViolationReport(BaseModel):
    """CSP violation report model following CSP Level 3 specification."""

    document_uri: str = Field(..., description="URI of the document that violated the policy")
    referrer: str = Field(default="", description="Referrer of the document")
    blocked_uri: str = Field(..., description="URI that was blocked")
    violated_directive: str = Field(..., description="Directive that was violated")
    effective_directive: str = Field(..., description="Effective directive that was violated")
    original_policy: str = Field(..., description="Original CSP policy")
    disposition: str = Field(default="enforce", description="Policy disposition (enforce/report)")
    status_code: int = Field(default=200, description="HTTP status code")
    script_sample: str = Field(default="", description="Sample of the blocked script")
    line_number: int = Field(default=0, description="Line number where violation occurred")
    column_number: int = Field(default=0, description="Column number where violation occurred")


class CSPReportWrapper(BaseModel):
    """CSP report wrapper as sent by browsers."""

    csp_report: CSPViolationReport = Field(..., description="The CSP violation report")


@router.post("/csp-report", include_in_schema=False)
async def handle_csp_violation(
    request: Request,
    report_data: dict[str, Any],
    db: Session = Depends(get_db)
) -> JSONResponse:
    """Handle Content Security Policy violation reports.
    
    This endpoint receives CSP violation reports from browsers and logs them
    for security monitoring and policy adjustment.
    
    Args:
        request: The HTTP request
        report_data: Raw CSP report data from browser
        db: Database session
        
    Returns:
        JSONResponse with acknowledgment
    """
    try:
        # Extract client information
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        # Parse and validate CSP report
        csp_report = None
        try:
            if "csp-report" in report_data:
                csp_report = CSPViolationReport(**report_data["csp-report"])
            else:
                # Some browsers send direct report format
                csp_report = CSPViolationReport(**report_data)
        except Exception as parse_error:
            logger.warning(
                "Failed to parse CSP violation report",
                extra={
                    'operation': 'csp_report_parse_error',
                    'client_ip': client_ip,
                    'parse_error': str(parse_error),
                    'raw_data': str(report_data)[:1000]  # Limit size
                }
            )
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Invalid CSP report format"}
            )

        # Log the CSP violation
        logger.warning(
            "CSP violation detected",
            extra={
                'operation': 'csp_violation_report',
                'client_ip': client_ip,
                'user_agent': user_agent,
                'document_uri': csp_report.document_uri,
                'blocked_uri': csp_report.blocked_uri,
                'violated_directive': csp_report.violated_directive,
                'effective_directive': csp_report.effective_directive,
                'disposition': csp_report.disposition,
                'script_sample': csp_report.script_sample[:200] if csp_report.script_sample else ""
            }
        )

        # Store security event in database
        try:
            security_event = SecurityEvent(
                user_id=None,  # CSP violations are often anonymous
                type="CSP_VIOLATION_REPORT",
                ip=client_ip,
                ua=user_agent
            )
            db.add(security_event)
            db.commit()

        except Exception as db_error:
            logger.error(
                "Failed to store CSP violation in database",
                extra={
                    'operation': 'csp_db_error',
                    'error': str(db_error)
                }
            )
            db.rollback()

        # Analyze violation for potential security threats
        threat_analysis = _analyze_csp_violation(csp_report, client_ip, user_agent)

        if threat_analysis["is_suspicious"]:
            logger.critical(
                "Suspicious CSP violation detected - potential attack",
                extra={
                    'operation': 'suspicious_csp_violation',
                    'client_ip': client_ip,
                    'threat_indicators': threat_analysis["indicators"],
                    'blocked_uri': csp_report.blocked_uri
                }
            )

        return JSONResponse(
            status_code=204,
            content=None,
            headers={
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY"
            }
        )

    except Exception as e:
        logger.error(
            "Error handling CSP violation report",
            exc_info=True,
            extra={
                'operation': 'csp_handler_error',
                'error_type': type(e).__name__
            }
        )

        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Internal error processing CSP report"}
        )


@router.post("/xss-report")
async def handle_xss_detection(
    request: Request,
    payload: dict[str, Any],
    db: Session = Depends(get_db)
) -> JSONResponse:
    """Handle XSS detection reports from client-side protection.
    
    Args:
        request: The HTTP request
        payload: XSS detection payload
        db: Database session
        
    Returns:
        JSONResponse with acknowledgment
    """
    try:
        # Extract client information
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        # Sanitize the report payload
        sanitized_payload = {}
        for key, value in payload.items():
            if isinstance(value, str):
                sanitized_payload[key] = input_sanitization_service.sanitize_text_input(value)
            else:
                sanitized_payload[key] = value

        # Log XSS detection
        logger.warning(
            "Client-side XSS detection reported",
            extra={
                'operation': 'client_xss_report',
                'client_ip': client_ip,
                'user_agent': user_agent,
                'payload': sanitized_payload
            }
        )

        # Store security event
        try:
            security_event = SecurityEvent(
                user_id=None,
                type="XSS_ATTEMPT_DETECTED",
                ip=client_ip,
                ua=user_agent
            )
            db.add(security_event)
            db.commit()

        except Exception as db_error:
            logger.error(f"Failed to store XSS detection event: {db_error}")
            db.rollback()

        return JSONResponse(
            status_code=204,
            content=None,
            headers={
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY"
            }
        )

    except Exception as e:
        logger.error(f"Error handling XSS detection report: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Internal error processing XSS report"}
        )


def _analyze_csp_violation(
    csp_report: CSPViolationReport,
    client_ip: str,
    user_agent: str
) -> dict[str, Any]:
    """Analyze CSP violation for potential security threats.
    
    Args:
        csp_report: The CSP violation report
        client_ip: Client IP address
        user_agent: User agent string
        
    Returns:
        Threat analysis results
    """
    indicators = []

    # Check for suspicious blocked URIs
    suspicious_patterns = [
        "javascript:",
        "data:text/html",
        "blob:",
        "eval(",
        "alert(",
        "confirm(",
        "prompt("
    ]

    blocked_uri = csp_report.blocked_uri.lower()
    for pattern in suspicious_patterns:
        if pattern in blocked_uri:
            indicators.append(f"Suspicious blocked URI pattern: {pattern}")

    # Check for script injection attempts
    if csp_report.script_sample:
        script_sample = csp_report.script_sample.lower()
        xss_patterns = ["<script", "javascript:", "onerror=", "onload="]
        for pattern in xss_patterns:
            if pattern in script_sample:
                indicators.append(f"XSS pattern in script sample: {pattern}")

    # Check for policy bypass attempts
    if "unsafe-eval" in blocked_uri or "unsafe-inline" in blocked_uri:
        indicators.append("Potential CSP bypass attempt")

    # Check for data exfiltration attempts
    if any(domain in blocked_uri for domain in ["bit.ly", "tinyurl", "t.co"]):
        indicators.append("Potential data exfiltration via URL shortener")

    return {
        "is_suspicious": len(indicators) > 0,
        "indicators": indicators,
        "threat_level": "high" if len(indicators) >= 2 else "medium" if indicators else "low"
    }
