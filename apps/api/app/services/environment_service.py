"""
Environment Management Service - Task 3.12
Ultra-Enterprise environment configuration and validation service

**Risk Assessment**: HIGH - Manages critical security configurations
**Compliance**: Turkish KVKV, GDPR Article 25, ISO 27001
**Security Level**: Ultra-Enterprise Banking-Grade
"""

from __future__ import annotations

import json
import time
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from ..core.environment import environment, validate_startup_configuration, log_environment_startup
from ..core.logging import get_logger

logger = get_logger(__name__)


class EnvironmentService:
    """
    Ultra-Enterprise Environment Management Service

    Provides centralized management of environment-specific features:
    - Configuration validation and monitoring
    - Dev-mode feature management
    - Production hardening enforcement
    - Security policy validation
    - Turkish KVKV compliance monitoring
    """

    def __init__(self):
        self._initialized = False
        self._startup_time = time.time()
        self._config_warnings: List[str] = []
        self._config_errors: List[str] = []

    async def initialize(self) -> None:
        """Initialize the environment service and validate configuration."""

        if self._initialized:
            return

        logger.info(
            "Initializing Ultra-Enterprise Environment Service",
            extra={
                "operation": "environment_service_init",
                "environment": environment.ENV,
                "dev_mode": environment.is_dev_mode,
            },
        )

        try:
            # Validate startup configuration
            validate_startup_configuration()

            # Log environment configuration
            log_environment_startup()

            # Perform additional service-level validations
            await self._validate_service_configuration()

            # Log successful initialization
            logger.info(
                "Environment service initialized successfully",
                extra={
                    "operation": "environment_service_initialized",
                    "environment": environment.ENV,
                    "initialization_time_ms": int((time.time() - self._startup_time) * 1000),
                    "config_summary": environment.get_environment_summary(),
                },
            )

            self._initialized = True

        except Exception as e:
            logger.error(
                "Failed to initialize environment service",
                exc_info=True,
                extra={
                    "operation": "environment_service_init_failed",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                },
            )
            raise

    async def _validate_service_configuration(self) -> None:
        """Perform service-level configuration validations."""

        # Clear previous warnings/errors
        self._config_warnings.clear()
        self._config_errors.clear()

        # Check for development-specific issues
        if environment.is_development:
            await self._validate_development_configuration()

        # Check for production-specific requirements
        if environment.is_production:
            await self._validate_production_configuration()

        # Check for staging-specific requirements
        if environment.is_staging:
            await self._validate_staging_configuration()

        # Turkish KVKV compliance validation
        await self._validate_kvkv_compliance()

        # Log warnings and errors
        for warning in self._config_warnings:
            logger.warning(
                f"Configuration warning: {warning}",
                extra={
                    "operation": "config_validation_warning",
                    "warning": warning,
                    "environment": environment.ENV,
                },
            )

        for error in self._config_errors:
            logger.error(
                f"Configuration error: {error}",
                extra={
                    "operation": "config_validation_error",
                    "error": error,
                    "environment": environment.ENV,
                },
            )

        # Raise exception if critical errors found
        if self._config_errors:
            raise RuntimeError(f"Critical configuration errors: {', '.join(self._config_errors)}")

    async def _validate_development_configuration(self) -> None:
        """Validate development environment configuration."""

        # Check if dev mode is properly configured
        if not environment.is_dev_mode and environment.DEV_AUTH_BYPASS:
            self._config_warnings.append("DEV_AUTH_BYPASS enabled but DEV_MODE is disabled")

        # Check for insecure development settings
        if environment.is_dev_mode:
            dev_features = []
            if environment.DEV_AUTH_BYPASS:
                dev_features.append("auth_bypass")
            if environment.DEV_DETAILED_ERRORS:
                dev_features.append("detailed_errors")
            if environment.CSRF_DEV_LOCALHOST_BYPASS:
                dev_features.append("csrf_localhost_bypass")

            logger.info(
                "Development mode features enabled",
                extra={
                    "operation": "dev_mode_features_active",
                    "features": dev_features,
                    "warning": "These features must never be enabled in production",
                },
            )

    async def _validate_production_configuration(self) -> None:
        """Validate production environment configuration."""

        # Check for insecure production configurations
        if not environment.should_force_https:
            self._config_warnings.append("HTTPS enforcement is disabled in production environment")

        if not environment.should_use_secure_cookies:
            self._config_errors.append("Secure cookies must be enabled in production environment")

        if environment.DEBUG:
            self._config_warnings.append("DEBUG mode is enabled in production environment")

        if environment.DEV_AUTH_BYPASS:
            self._config_errors.append("Authentication bypass must be disabled in production")

        # Check OAuth configuration
        if environment.GOOGLE_OAUTH_ENABLED:
            if not environment.GOOGLE_CLIENT_ID:
                self._config_errors.append(
                    "GOOGLE_CLIENT_ID is required when OAuth is enabled in production"
                )

            if not environment.GOOGLE_CLIENT_SECRET:
                self._config_errors.append(
                    "GOOGLE_CLIENT_SECRET is required when OAuth is enabled in production"
                )

        # Check audit logging
        if not environment.AUDIT_LOG_ENABLED:
            self._config_errors.append("Audit logging must be enabled in production for compliance")

        if not environment.AUDIT_HASH_CHAIN_ENABLED:
            self._config_errors.append(
                "Audit hash chain must be enabled in production for integrity"
            )

    async def _validate_staging_configuration(self) -> None:
        """Validate staging environment configuration."""

        # Staging should be production-like
        if environment.DEV_AUTH_BYPASS:
            self._config_warnings.append(
                "Authentication bypass should be disabled in staging environment"
            )

        if not environment.should_use_secure_cookies:
            self._config_warnings.append(
                "Secure cookies should be enabled in staging for production testing"
            )

    async def _validate_kvkv_compliance(self) -> None:
        """Validate Turkish KVKV compliance settings."""

        # Check data retention settings
        if environment.KVKV_DATA_RETENTION_DAYS < 365:
            self._config_warnings.append(
                "KVKV data retention period is less than 1 year - ensure compliance"
            )

        # Check audit logging for KVKV
        if not environment.KVKV_AUDIT_LOG_ENABLED:
            self._config_errors.append("KVKV audit logging must be enabled for Turkish compliance")

        # Check PII masking
        if not environment.KVKV_PII_MASKING_ENABLED:
            self._config_warnings.append(
                "KVKV PII masking should be enabled for personal data protection"
            )

        # Check consent requirements
        if not environment.KVKV_CONSENT_REQUIRED:
            self._config_warnings.append(
                "KVKV consent requirements should be enabled for compliance"
            )

    def get_environment_status(self) -> Dict[str, Any]:
        """Get comprehensive environment status information."""

        return {
            "environment": {
                "mode": str(environment.ENV),
                "dev_mode_enabled": environment.is_dev_mode,
                "production_hardening": environment.PRODUCTION_HARDENING_ENABLED,
                "security_level": str(environment.SECURITY_LEVEL),
                "initialized": self._initialized,
                "uptime_seconds": int(time.time() - self._startup_time),
            },
            "security_features": {
                "csrf_protection": True,
                "rate_limiting": True,
                "audit_logging": environment.AUDIT_LOG_ENABLED,
                "security_headers": environment.SECURITY_CSP_ENABLED,
                "hsts_enabled": environment.SECURITY_HSTS_ENABLED,
                "xss_detection": environment.SECURITY_XSS_DETECTION_ENABLED,
            },
            "dev_features": {
                "auth_bypass": environment.DEV_AUTH_BYPASS if environment.is_development else False,
                "detailed_errors": environment.DEV_DETAILED_ERRORS
                if environment.is_development
                else False,
                "response_annotations": environment.DEV_RESPONSE_ANNOTATIONS
                if environment.is_development
                else False,
                "csrf_localhost_bypass": environment.CSRF_DEV_LOCALHOST_BYPASS
                if environment.is_development
                else False,
                "mock_external_services": environment.DEV_MOCK_EXTERNAL_SERVICES
                if environment.is_development
                else False,
            },
            "production_hardening": {
                "force_https": environment.should_force_https,
                "secure_cookies": environment.should_use_secure_cookies,
                "mask_errors": environment.should_mask_errors,
                "disable_debug_endpoints": environment.PROD_DISABLE_DEBUG_ENDPOINTS
                if environment.is_production
                else False,
            },
            "kvkv_compliance": {
                "audit_logging": environment.KVKV_AUDIT_LOG_ENABLED,
                "pii_masking": environment.KVKV_PII_MASKING_ENABLED,
                "consent_required": environment.KVKV_CONSENT_REQUIRED,
                "data_retention_days": environment.KVKV_DATA_RETENTION_DAYS,
                "compliance_status": environment.kvkv_compliance_status_tr,
            },
            "oauth_configuration": {
                "google_oauth_enabled": environment.GOOGLE_OAUTH_ENABLED,
                "client_configured": bool(environment.GOOGLE_CLIENT_ID),
                "discovery_url": environment.GOOGLE_DISCOVERY_URL,
            },
            "monitoring": {
                "sentry_enabled": bool(environment.SENTRY_DSN),
                "otel_enabled": bool(environment.OTEL_EXPORTER_OTLP_ENDPOINT),
                "service_name": environment.OTEL_SERVICE_NAME,
            },
            "warnings": self._config_warnings,
            "errors": self._config_errors,
            "last_validation": datetime.now(timezone.utc).isoformat(),
            "turkish_status": {
                "environment": environment.environment_display_tr,
                "security_level": environment.security_level_display_tr,
                "kvkv_compliance": environment.kvkv_compliance_status_tr,
            },
        }

    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if a specific feature is enabled in current environment."""

        feature_map = {
            # Development features
            "dev_mode": environment.is_dev_mode,
            "auth_bypass": environment.DEV_AUTH_BYPASS and environment.is_development,
            "detailed_errors": environment.DEV_DETAILED_ERRORS and environment.is_development,
            "response_annotations": environment.DEV_RESPONSE_ANNOTATIONS
            and environment.is_development,
            "csrf_localhost_bypass": environment.CSRF_DEV_LOCALHOST_BYPASS
            and environment.is_development,
            # Security features
            "csrf_protection": True,  # Always enabled
            "rate_limiting": True,  # Always enabled
            "audit_logging": environment.AUDIT_LOG_ENABLED,
            "security_headers": environment.SECURITY_CSP_ENABLED,
            "xss_detection": environment.SECURITY_XSS_DETECTION_ENABLED,
            "hsts": environment.SECURITY_HSTS_ENABLED,
            # Production hardening
            "force_https": environment.should_force_https,
            "secure_cookies": environment.should_use_secure_cookies,
            "mask_errors": environment.should_mask_errors,
            # KVKV compliance
            "kvkv_audit": environment.KVKV_AUDIT_LOG_ENABLED,
            "kvkv_pii_masking": environment.KVKV_PII_MASKING_ENABLED,
            "kvkv_consent": environment.KVKV_CONSENT_REQUIRED,
            # OAuth
            "google_oauth": environment.GOOGLE_OAUTH_ENABLED,
            # Monitoring
            "sentry": bool(environment.SENTRY_DSN),
            "otel": bool(environment.OTEL_EXPORTER_OTLP_ENDPOINT),
        }

        return feature_map.get(feature_name, False)

    def get_security_policy(self) -> Dict[str, Any]:
        """Get current security policy configuration."""

        return {
            "environment": str(environment.ENV),
            "security_level": str(environment.SECURITY_LEVEL),
            "authentication": {
                "bypass_enabled": self.is_feature_enabled("auth_bypass"),
                "jwt_algorithm": environment.JWT_ALGORITHM,
                "access_token_expire_minutes": environment.JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
                "session_timeout_minutes": environment.SESSION_TIMEOUT_MINUTES,
            },
            "csrf_protection": {
                "enabled": True,
                "localhost_bypass": self.is_feature_enabled("csrf_localhost_bypass"),
                "token_lifetime_seconds": environment.CSRF_TOKEN_LIFETIME_SECONDS,
                "rate_limit_per_minute": environment.CSRF_RATE_LIMIT_PER_MINUTE,
            },
            "rate_limiting": {
                "global_limit": environment.RATE_LIMIT_GLOBAL,
                "auth_limit": environment.RATE_LIMIT_AUTH,
                "api_limit": environment.RATE_LIMIT_API,
                "brute_force_max_attempts": environment.BRUTE_FORCE_MAX_ATTEMPTS,
                "lockout_duration_seconds": environment.BRUTE_FORCE_LOCKOUT_DURATION,
            },
            "security_headers": {
                "csp_enabled": environment.SECURITY_CSP_ENABLED,
                "hsts_enabled": environment.SECURITY_HSTS_ENABLED,
                "hsts_max_age": environment.SECURITY_HSTS_MAX_AGE,
                "xss_detection": environment.SECURITY_XSS_DETECTION_ENABLED,
            },
            "cookies": {
                "secure": environment.should_use_secure_cookies,
                "httponly": environment.SESSION_COOKIE_HTTPONLY,
                "samesite": environment.SESSION_COOKIE_SAMESITE,
            },
            "cors": {
                "allowed_origins": environment.CORS_ALLOWED_ORIGINS,
                "allow_credentials": environment.CORS_ALLOW_CREDENTIALS,
                "max_age": environment.CORS_MAX_AGE,
            },
            "audit_logging": {
                "enabled": environment.AUDIT_LOG_ENABLED,
                "retention_days": environment.AUDIT_LOG_RETENTION_DAYS,
                "hash_chain_enabled": environment.AUDIT_HASH_CHAIN_ENABLED,
                "real_time_monitoring": environment.AUDIT_REAL_TIME_MONITORING,
            },
            "kvkv_compliance": {
                "audit_enabled": environment.KVKV_AUDIT_LOG_ENABLED,
                "pii_masking": environment.KVKV_PII_MASKING_ENABLED,
                "consent_required": environment.KVKV_CONSENT_REQUIRED,
                "data_retention_days": environment.KVKV_DATA_RETENTION_DAYS,
            },
        }

    async def validate_runtime_security(self) -> Tuple[bool, List[str]]:
        """Perform runtime security validation."""

        issues = []

        # Check for critical security issues
        if environment.is_production and environment.DEV_MODE:
            issues.append("Development mode enabled in production")

        if environment.is_production and environment.DEV_AUTH_BYPASS:
            issues.append("Authentication bypass enabled in production")

        if environment.is_production and not environment.should_use_secure_cookies:
            issues.append("Insecure cookies in production")

        if environment.is_production and not environment.should_force_https:
            issues.append("HTTPS not enforced in production")

        # Check KVKV compliance
        if not environment.KVKV_AUDIT_LOG_ENABLED:
            issues.append("KVKV audit logging disabled")

        # Log security validation results
        if issues:
            logger.warning(
                "Runtime security validation found issues",
                extra={
                    "operation": "runtime_security_validation",
                    "issues": issues,
                    "environment": environment.ENV,
                },
            )
            return False, issues

        logger.debug(
            "Runtime security validation passed",
            extra={
                "operation": "runtime_security_validation_passed",
                "environment": environment.ENV,
            },
        )

        return True, []


# Global environment service instance
environment_service = EnvironmentService()
