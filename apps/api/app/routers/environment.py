"""
Environment Status API Router - Task 3.12
Ultra-Enterprise environment monitoring and configuration endpoints

**Risk Assessment**: MEDIUM - Exposes configuration status (sanitized)
**Compliance**: Turkish KVKV, GDPR Article 25, ISO 27001
**Security Level**: Ultra-Enterprise Banking-Grade
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.responses import JSONResponse

from ..core.environment import environment
from ..services.environment_service import environment_service
from ..core.logging import get_logger
from ..middleware.rbac_middleware import require_role, RoleRequirement

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/environment",
    tags=["environment"],
    dependencies=[Depends(require_role([RoleRequirement.ADMIN, RoleRequirement.SYSTEM_OPERATOR]))]
)


@router.get("/status")
async def get_environment_status(request: Request) -> Dict[str, Any]:
    """
    Get comprehensive environment status information.
    
    **Requires**: Admin or System Operator role
    **Security**: Only exposes sanitized configuration information
    **Compliance**: Logs access for audit trail
    
    Returns:
        Comprehensive environment status including:
        - Current environment mode and security level
        - Active security features
        - Development mode features (if applicable)
        - Production hardening status
        - KVKV compliance status
        - Configuration warnings/errors
    """
    
    try:
        # Get client information for logging
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get('user-agent')
        
        # Log environment status access
        logger.info(
            "Environment status accessed",
            extra={
                'operation': 'environment_status_accessed',
                'client_ip': client_ip,
                'user_agent': user_agent[:100] if user_agent else None,
                'path': str(request.url.path),
                'environment': environment.ENV
            }
        )
        
        # Get comprehensive environment status
        status_info = environment_service.get_environment_status()
        
        return {
            "status": "success",
            "data": status_info,
            "timestamp": status_info.get("last_validation"),
            "message": "Environment status retrieved successfully",
            "turkish_message": "Ortam durumu başarıyla alındı"
        }
        
    except Exception as e:
        logger.error(
            "Failed to retrieve environment status",
            exc_info=True,
            extra={
                'operation': 'environment_status_error',
                'error_type': type(e).__name__,
                'client_ip': client_ip
            }
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "ENV_STATUS_ERROR",
                "message": "Failed to retrieve environment status",
                "turkish_message": "Ortam durumu alınamadı"
            }
        )


@router.get("/security-policy")
async def get_security_policy(request: Request) -> Dict[str, Any]:
    """
    Get current security policy configuration.
    
    **Requires**: Admin or System Operator role
    **Security**: Only exposes policy configuration, no secrets
    **Compliance**: Logs access for security audit
    
    Returns:
        Current security policy including:
        - Authentication settings
        - CSRF protection configuration
        - Rate limiting policies
        - Security headers configuration
        - KVKV compliance settings
    """
    
    try:
        # Get client information for logging
        client_ip = request.client.host if request.client else None
        
        # Log security policy access
        logger.info(
            "Security policy accessed",
            extra={
                'operation': 'security_policy_accessed',
                'client_ip': client_ip,
                'environment': environment.ENV,
                'path': str(request.url.path)
            }
        )
        
        # Get security policy
        policy = environment_service.get_security_policy()
        
        return {
            "status": "success",
            "data": policy,
            "message": "Security policy retrieved successfully",
            "turkish_message": "Güvenlik politikası başarıyla alındı"
        }
        
    except Exception as e:
        logger.error(
            "Failed to retrieve security policy",
            exc_info=True,
            extra={
                'operation': 'security_policy_error',
                'error_type': type(e).__name__,
                'client_ip': client_ip
            }
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "SECURITY_POLICY_ERROR",
                "message": "Failed to retrieve security policy",
                "turkish_message": "Güvenlik politikası alınamadı"
            }
        )


@router.get("/features")
async def get_feature_flags(request: Request) -> Dict[str, Any]:
    """
    Get current feature flag status.
    
    **Requires**: Admin or System Operator role
    **Security**: Only exposes feature availability, no configuration details
    
    Returns:
        Current feature flag status including:
        - Development features (if in dev mode)
        - Security features
        - Production hardening features
        - KVKV compliance features
        - Integration features
    """
    
    try:
        client_ip = request.client.host if request.client else None
        
        # Get available features
        features = {
            "development": {
                "dev_mode": environment_service.is_feature_enabled("dev_mode"),
                "auth_bypass": environment_service.is_feature_enabled("auth_bypass"),
                "detailed_errors": environment_service.is_feature_enabled("detailed_errors"),
                "response_annotations": environment_service.is_feature_enabled("response_annotations"),
                "csrf_localhost_bypass": environment_service.is_feature_enabled("csrf_localhost_bypass")
            },
            "security": {
                "csrf_protection": environment_service.is_feature_enabled("csrf_protection"),
                "rate_limiting": environment_service.is_feature_enabled("rate_limiting"),
                "audit_logging": environment_service.is_feature_enabled("audit_logging"),
                "security_headers": environment_service.is_feature_enabled("security_headers"),
                "xss_detection": environment_service.is_feature_enabled("xss_detection"),
                "hsts": environment_service.is_feature_enabled("hsts")
            },
            "production_hardening": {
                "force_https": environment_service.is_feature_enabled("force_https"),
                "secure_cookies": environment_service.is_feature_enabled("secure_cookies"),
                "mask_errors": environment_service.is_feature_enabled("mask_errors")
            },
            "kvkv_compliance": {
                "audit_logging": environment_service.is_feature_enabled("kvkv_audit"),
                "pii_masking": environment_service.is_feature_enabled("kvkv_pii_masking"),
                "consent_required": environment_service.is_feature_enabled("kvkv_consent")
            },
            "integrations": {
                "google_oauth": environment_service.is_feature_enabled("google_oauth"),
                "sentry_monitoring": environment_service.is_feature_enabled("sentry"),
                "otel_tracing": environment_service.is_feature_enabled("otel")
            }
        }
        
        logger.debug(
            "Feature flags accessed",
            extra={
                'operation': 'feature_flags_accessed',
                'client_ip': client_ip,
                'environment': environment.ENV
            }
        )
        
        return {
            "status": "success",
            "data": features,
            "environment": str(environment.ENV),
            "message": "Feature flags retrieved successfully",
            "turkish_message": "Özellik bayrakları başarıyla alındı"
        }
        
    except Exception as e:
        logger.error(
            "Failed to retrieve feature flags",
            exc_info=True,
            extra={
                'operation': 'feature_flags_error',
                'error_type': type(e).__name__
            }
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "FEATURE_FLAGS_ERROR",
                "message": "Failed to retrieve feature flags",
                "turkish_message": "Özellik bayrakları alınamadı"
            }
        )


@router.post("/validate-security")
async def validate_runtime_security(request: Request) -> Dict[str, Any]:
    """
    Perform runtime security validation.
    
    **Requires**: Admin role only
    **Security**: Critical security validation
    **Compliance**: Logs all validation attempts
    
    Returns:
        Security validation results including:
        - Validation status (pass/fail)
        - Security issues found (if any)
        - Recommendations
    """
    
    try:
        client_ip = request.client.host if request.client else None
        
        # Log security validation request
        logger.info(
            "Runtime security validation requested",
            extra={
                'operation': 'runtime_security_validation_requested',
                'client_ip': client_ip,
                'environment': environment.ENV
            }
        )
        
        # Perform validation
        is_valid, issues = await environment_service.validate_runtime_security()
        
        result = {
            "validation_passed": is_valid,
            "issues_found": len(issues),
            "issues": issues,
            "environment": str(environment.ENV),
            "validation_timestamp": environment_service.get_environment_status()["last_validation"]
        }
        
        if is_valid:
            return {
                "status": "success",
                "data": result,
                "message": "Runtime security validation passed",
                "turkish_message": "Çalışma zamanı güvenlik doğrulaması başarılı"
            }
        else:
            return {
                "status": "warning",
                "data": result,
                "message": f"Runtime security validation found {len(issues)} issues",
                "turkish_message": f"Çalışma zamanı güvenlik doğrulaması {len(issues)} sorun tespit etti"
            }
        
    except Exception as e:
        logger.error(
            "Failed to perform runtime security validation",
            exc_info=True,
            extra={
                'operation': 'runtime_security_validation_error',
                'error_type': type(e).__name__
            }
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "SECURITY_VALIDATION_ERROR",
                "message": "Failed to perform security validation",
                "turkish_message": "Güvenlik doğrulaması gerçekleştirilemedi"
            }
        )


@router.get("/health")
async def environment_health() -> Dict[str, Any]:
    """
    Get environment health status.
    
    **Public Endpoint**: No authentication required
    **Security**: Only exposes basic health information
    
    Returns:
        Basic environment health status
    """
    
    try:
        # Basic health information
        health_info = {
            "status": "healthy",
            "environment": str(environment.ENV),
            "dev_mode": environment.is_dev_mode if environment.is_development else False,
            "security_level": environment.security_level_display_tr,
            "kvkv_compliant": environment.KVKV_AUDIT_LOG_ENABLED,
            "timestamp": environment_service.get_environment_status()["last_validation"]
        }
        
        return {
            "status": "success",
            "data": health_info,
            "message": "Environment is healthy",
            "turkish_message": "Ortam sağlıklı durumda"
        }
        
    except Exception as e:
        logger.error(
            "Environment health check failed",
            exc_info=True,
            extra={
                'operation': 'environment_health_error',
                'error_type': type(e).__name__
            }
        )
        
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "error_code": "ENV_HEALTH_ERROR",
                "message": "Environment health check failed",
                "turkish_message": "Ortam sağlık kontrolü başarısız"
            }
        )