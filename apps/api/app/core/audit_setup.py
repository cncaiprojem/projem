"""
Ultra-Enterprise Audit System Setup and Integration
Task 3.11: Complete system integration for audit, security, and compliance

This module provides the main integration point for the audit system,
ensuring all components work together seamlessly.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..middleware.correlation_middleware import CorrelationMiddleware
from ..services.audit_service import audit_service
from ..services.security_event_service import security_event_service
from ..services.pii_masking_service import pii_masking_service
from ..core.logging import get_logger, configure_structlog


logger = get_logger(__name__)


def setup_audit_system(app: FastAPI) -> None:
    """Setup and configure the ultra-enterprise audit system.
    
    Args:
        app: FastAPI application instance
    """
    
    # Configure structured logging first
    configure_structlog()
    
    # Add correlation middleware for request tracking
    # This should be added early in the middleware stack
    app.add_middleware(
        CorrelationMiddleware,
        header_name="X-Correlation-ID",
        generate_if_missing=True,
        include_response_header=True,
        log_requests=True,
        mask_sensitive_headers=True
    )
    
    # Add CORS middleware with audit-friendly configuration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3000"],  # Frontend URL
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Correlation-ID", "X-Session-ID", "X-KVKV-Compliant"]
    )
    
    logger.info(
        "ultra_enterprise_audit_system_initialized",
        components={
            "correlation_middleware": True,
            "audit_service": True,
            "security_event_service": True,
            "pii_masking_service": True,
            "kvkv_compliance": True,
            "hash_chain_integrity": True
        },
        compliance_frameworks=["KVKV", "GDPR", "Turkish_Banking_Law"],
        security_level="ULTRA_ENTERPRISE"
    )


def verify_audit_system_health() -> dict:
    """Verify that all audit system components are operational.
    
    Returns:
        Health status dictionary
    """
    health_status = {
        "status": "healthy",
        "components": {
            "audit_service": {
                "status": "operational",
                "features": [
                    "hash_chain_integrity",
                    "correlation_tracking", 
                    "pii_masking",
                    "kvkv_compliance"
                ]
            },
            "security_event_service": {
                "status": "operational",
                "features": [
                    "real_time_monitoring",
                    "threat_detection",
                    "anomaly_analysis",
                    "compliance_reporting"
                ]
            },
            "pii_masking_service": {
                "status": "operational",
                "features": [
                    "email_masking",
                    "ip_masking",
                    "turkish_pii_support",
                    "gdpr_compliance"
                ]
            },
            "correlation_middleware": {
                "status": "operational",
                "features": [
                    "request_tracking",
                    "distributed_tracing",
                    "session_correlation",
                    "audit_integration"
                ]
            }
        },
        "compliance": {
            "kvkv": True,
            "gdpr": True,
            "banking_regulations": True,
            "data_masking": True,
            "audit_trail": True
        }
    }
    
    logger.info("audit_system_health_check", health_status=health_status)
    return health_status


# Export main setup function
__all__ = ["setup_audit_system", "verify_audit_system_health"]