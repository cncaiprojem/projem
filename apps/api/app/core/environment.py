"""
Ultra-Enterprise Environment Configuration with Dev-Mode Toggles and Production Hardening
Implements Task 3.12 with banking-level security standards and Turkish KVKV compliance

**Risk Assessment**: CRITICAL - Core security configuration system
**Compliance**: Turkish KVKV, GDPR Article 25, ISO 27001, Banking Regulations
**Security Level**: Ultra-Enterprise Banking-Grade
"""

from __future__ import annotations

import os
import json
import secrets
import warnings
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from decimal import Decimal

from pydantic import Field, model_validator, ConfigDict, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .logging import get_logger

logger = get_logger(__name__)


class EnvironmentMode(str, Enum):
    """Environment operation modes with strict security policies."""
    DEVELOPMENT = "development"
    STAGING = "staging" 
    PRODUCTION = "production"
    

class SecurityLevel(str, Enum):
    """Security enforcement levels."""
    MINIMAL = "minimal"      # Development only
    STANDARD = "standard"    # Staging
    MAXIMUM = "maximum"      # Production


class UltraEnterpriseEnvironment(BaseSettings):
    """
    Ultra-Enterprise Environment Configuration with Dev-Mode Toggles
    
    Implements Task 3.12 requirements:
    - Dev-mode behaviors with relaxed guards
    - Production hardening enforcement
    - Environment-specific security controls
    - Turkish KVKV compliance
    - Banking-level security standards
    
    **SECURITY CRITICAL**: This class controls all security behaviors
    """
    
    model_config = SettingsConfigDict(
        env_file=[".env", ".env.local"],
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
        env_prefix="",
        env_parse_none_str="",
        # Disable JSON parsing for list fields to use validators instead
        env_ignore_empty=True,
    )
    
    # ===================================================================
    # CORE ENVIRONMENT CONFIGURATION (Task 3.12)
    # ===================================================================
    
    ENV: EnvironmentMode = Field(
        default=EnvironmentMode.DEVELOPMENT,
        description="Current environment mode"
    )
    
    DEV_MODE: bool = Field(
        default=False,
        description="Enable development mode with relaxed security (NEVER use in production)"
    )
    
    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode with detailed error traces"
    )
    
    PRODUCTION_HARDENING_ENABLED: bool = Field(
        default=True,
        description="Enable production security hardening features"
    )
    
    SECURITY_LEVEL: SecurityLevel = Field(
        default=SecurityLevel.MAXIMUM,
        description="Security enforcement level"
    )
    
    # ===================================================================
    # APPLICATION CORE SETTINGS  
    # ===================================================================
    
    SECRET_KEY: str = Field(
        default="dev-secret-key-change-in-production-minimum-32-chars",
        description="Main application secret key"
    )
    
    API_PORT: int = Field(default=8000, description="API server port")
    WEB_PORT: int = Field(default=3000, description="Web server port")
    
    SYSTEM_USER_ID: int = Field(
        default=1,
        description="System user ID for automated operations (batch processing, etc.)"
    )
    
    # ===================================================================
    # DATABASE CONFIGURATION
    # ===================================================================
    
    DATABASE_URL: str = Field(
        default="postgresql+psycopg2://freecad_dev:dev_password@postgres:5432/freecad_dev",
        description="Database connection URL"
    )
    
    DB_CONNECTION_POOL_SIZE: int = Field(default=20, description="DB connection pool size")
    DB_CONNECTION_TIMEOUT: int = Field(default=30, description="DB connection timeout")
    DB_QUERY_TIMEOUT: int = Field(default=60, description="DB query timeout")
    
    # ===================================================================
    # REDIS & CACHING CONFIGURATION
    # ===================================================================
    
    REDIS_URL: str = Field(
        default="redis://redis:6379/0",
        description="Redis connection URL"
    )
    
    REDIS_CONNECTION_POOL_SIZE: int = Field(default=50, description="Redis connection pool")
    REDIS_CONNECTION_TIMEOUT: int = Field(default=5, description="Redis connection timeout")
    
    # ===================================================================
    # JWT & AUTHENTICATION CONFIGURATION (Tasks 3.1, 3.2, 3.3)
    # ===================================================================
    
    JWT_SECRET_KEY: Optional[str] = Field(
        default=None,
        description="JWT signing secret (separate from main secret)"
    )
    
    JWT_ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=30, description="JWT access token lifetime")
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = Field(default=7, description="JWT refresh token lifetime")
    JWT_ISSUER: str = Field(default="freecad-ultra-enterprise", description="JWT issuer")
    JWT_AUDIENCE: str = Field(default="freecad-banking-users", description="JWT audience")
    
    # Session Configuration (Task 3.2, 3.3)
    SESSION_TIMEOUT_MINUTES: int = Field(default=30, description="Session timeout")
    SESSION_ABSOLUTE_TIMEOUT_MINUTES: int = Field(default=480, description="Absolute session timeout")
    SESSION_COOKIE_NAME: str = Field(default="session_id", description="Session cookie name")
    SESSION_COOKIE_SECURE: Optional[bool] = Field(
        default=None,  # Auto-determined by environment
        description="Secure cookie flag (auto-determined by environment)"
    )
    SESSION_COOKIE_HTTPONLY: bool = Field(default=True, description="HTTP-only cookie flag")
    SESSION_COOKIE_SAMESITE: str = Field(default="strict", description="SameSite cookie attribute")
    
    # ===================================================================
    # CSRF PROTECTION CONFIGURATION (Task 3.8)
    # ===================================================================
    
    CSRF_SECRET_KEY: str = Field(
        default="dev-csrf-hmac-key-ultra-secure-banking-grade-change-in-production",
        description="CSRF token HMAC secret key"
    )
    
    CSRF_TOKEN_LIFETIME_SECONDS: int = Field(default=7200, description="CSRF token lifetime")
    CSRF_RATE_LIMIT_PER_MINUTE: int = Field(default=60, description="CSRF token rate limit")
    CSRF_REQUIRE_AUTH: bool = Field(default=True, description="Require auth for CSRF")
    CSRF_DEV_LOCALHOST_BYPASS: bool = Field(
        default=False,
        description="Bypass CSRF for localhost in dev mode (Task 3.12)"
    )
    
    # ===================================================================
    # CORS CONFIGURATION
    # ===================================================================
    
    CORS_ALLOWED_ORIGINS: Union[str, List[str]] = Field(
        default=["http://localhost:3000"],
        description="Allowed CORS origins"
    )
    
    CORS_ALLOWED_METHODS: Union[str, List[str]] = Field(
        default=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        description="Allowed CORS methods"
    )
    
    CORS_ALLOWED_HEADERS: Union[str, List[str]] = Field(
        default=[
            "Accept", "Accept-Language", "Content-Language", 
            "Content-Type", "Authorization", "X-Requested-With", 
            "X-CSRF-Token", "X-Request-ID"
        ],
        description="Allowed CORS headers"
    )
    
    CORS_EXPOSE_HEADERS: Union[str, List[str]] = Field(
        default=["X-Total-Count", "X-Page-Count", "X-Request-ID"],
        description="Headers exposed to the browser in CORS responses"
    )
    
    CORS_ALLOW_CREDENTIALS: bool = Field(default=True, description="Allow CORS credentials")
    CORS_MAX_AGE: int = Field(default=3600, description="CORS preflight cache time")
    
    # ===================================================================
    # RATE LIMITING CONFIGURATION (Task 3.9)
    # ===================================================================
    
    RATE_LIMIT_GLOBAL: str = Field(default="1000/hour", description="Global rate limit")
    RATE_LIMIT_AUTH: str = Field(default="10/minute", description="Auth endpoint rate limit")
    RATE_LIMIT_API: str = Field(default="300/hour", description="API endpoint rate limit")
    
    # Brute Force Protection
    BRUTE_FORCE_MAX_ATTEMPTS: int = Field(default=5, description="Max failed login attempts")
    BRUTE_FORCE_LOCKOUT_DURATION: int = Field(default=900, description="Account lockout duration")
    BRUTE_FORCE_RESET_TIME: int = Field(default=3600, description="Failed attempt reset time")
    
    # ===================================================================
    # SECURITY HEADERS CONFIGURATION (Task 3.10)
    # ===================================================================
    
    SECURITY_HSTS_ENABLED: bool = Field(default=True, description="Enable HSTS headers")
    SECURITY_HSTS_MAX_AGE: int = Field(default=31536000, description="HSTS max age")
    SECURITY_CSP_ENABLED: bool = Field(default=True, description="Enable CSP headers")
    SECURITY_CSP_REPORT_URI: Optional[str] = Field(
        default="/api/security/csp-report",
        description="CSP violation report URI"
    )
    SECURITY_INPUT_VALIDATION_ENABLED: bool = Field(
        default=True, 
        description="Enable input validation"
    )
    SECURITY_XSS_DETECTION_ENABLED: bool = Field(
        default=True,
        description="Enable XSS detection"
    )
    
    # ===================================================================
    # PAYMENT PROVIDERS CONFIGURATION (Task 4.6)
    # ===================================================================
    
    # Stripe Configuration
    STRIPE_SECRET_KEY: Optional[str] = Field(
        default=None, 
        description="Stripe secret key for API calls"
    )
    STRIPE_WEBHOOK_SECRET: Optional[str] = Field(
        default=None,
        description="Stripe webhook endpoint secret"
    )
    STRIPE_ENVIRONMENT: str = Field(
        default="test",
        description="Stripe environment (test/live)"
    )
    
    # Payment Configuration
    DEFAULT_PAYMENT_PROVIDER: str = Field(
        default="mock",
        description="Default payment provider (stripe/mock)"
    )
    PAYMENT_WEBHOOK_TIMEOUT: int = Field(
        default=30,
        description="Payment webhook processing timeout in seconds"
    )
    
    # ===================================================================
    # OAUTH2 & GOOGLE OIDC CONFIGURATION (Task 3.5)
    # ===================================================================
    
    GOOGLE_OAUTH_ENABLED: bool = Field(default=True, description="Enable Google OAuth")
    GOOGLE_CLIENT_ID: Optional[str] = Field(default=None, description="Google OAuth client ID")
    GOOGLE_CLIENT_SECRET: Optional[str] = Field(default=None, description="Google OAuth secret")
    GOOGLE_DISCOVERY_URL: str = Field(
        default="https://accounts.google.com/.well-known/openid-configuration",
        description="Google OIDC discovery URL"
    )
    
    # OAuth Security Settings
    OAUTH_STATE_EXPIRE_MINUTES: int = Field(default=15, description="OAuth state expiry")
    OAUTH_PKCE_VERIFIER_EXPIRE_MINUTES: int = Field(default=15, description="PKCE verifier expiry")
    OAUTH_CALLBACK_TIMEOUT_SECONDS: int = Field(default=30, description="OAuth callback timeout")
    
    # ===================================================================
    # TURKISH KVKV COMPLIANCE CONFIGURATION
    # ===================================================================
    
    KVKV_DATA_RETENTION_DAYS: int = Field(
        default=2555,  # 7 years
        description="KVKV data retention period"
    )
    
    KVKV_PII_MASKING_ENABLED: bool = Field(
        default=True,
        description="Enable PII masking for KVKV"
    )
    
    KVKV_AUDIT_LOG_ENABLED: bool = Field(
        default=True,
        description="Enable KVKV audit logging"
    )
    
    KVKV_CONSENT_REQUIRED: bool = Field(
        default=True,
        description="Require explicit user consent"
    )
    
    # ===================================================================
    # AUDIT & SECURITY EVENT LOGGING (Task 3.11)
    # ===================================================================
    
    AUDIT_LOG_ENABLED: bool = Field(default=True, description="Enable audit logging")
    AUDIT_LOG_RETENTION_DAYS: int = Field(default=2555, description="Audit log retention")
    AUDIT_HASH_CHAIN_ENABLED: bool = Field(default=True, description="Enable audit hash chain")
    AUDIT_REAL_TIME_MONITORING: bool = Field(
        default=True,
        description="Enable real-time security monitoring"
    )
    
    SECURITY_EVENTS_ENABLED: bool = Field(
        default=True,
        description="Enable security event logging"
    )
    
    # ===================================================================
    # STORAGE & FILE HANDLING
    # ===================================================================
    
    AWS_ACCESS_KEY_ID: Optional[str] = Field(default=None, description="AWS/MinIO access key")
    AWS_SECRET_ACCESS_KEY: Optional[str] = Field(default=None, description="AWS/MinIO secret key")
    AWS_S3_ENDPOINT: Optional[str] = Field(default="http://minio:9000", description="S3 endpoint")
    AWS_S3_REGION: str = Field(default="us-east-1", description="S3 region")
    S3_BUCKET_NAME: str = Field(default="dev-artifacts", description="S3 bucket name")
    
    # ===================================================================
    # AI ADAPTER CONFIGURATION - TASK 7.2
    # ===================================================================
    
    AI_PROVIDER: str = Field(
        default="openai",
        description="AI provider (openai/azure)"
    )
    
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        description="OpenAI API key"
    )
    
    OPENAI_MODEL: str = Field(
        default="gpt-4",
        description="OpenAI model to use"
    )
    
    AZURE_API_KEY: Optional[str] = Field(
        default=None,
        description="Azure OpenAI API key"
    )
    
    AZURE_API_BASE: Optional[str] = Field(
        default=None,
        description="Azure OpenAI endpoint"
    )
    
    AZURE_DEPLOYMENT_NAME: str = Field(
        default="gpt-4",
        description="Azure OpenAI deployment name"
    )
    
    AI_MAX_TOKENS: int = Field(
        default=2000,
        description="Maximum tokens for AI response"
    )
    
    AI_TIMEOUT_SECONDS: int = Field(
        default=20,
        description="AI request timeout in seconds"
    )
    
    AI_TEMPERATURE: float = Field(
        default=0.3,
        description="AI temperature for response generation"
    )
    
    # ===================================================================
    # CLAMAV MALWARE SCANNING - TASK 5.6
    # ===================================================================
    
    CLAMAV_ENABLED: bool = Field(
        default=True,
        description="Enable ClamAV malware scanning for uploaded files"
    )
    
    CLAMAV_HOST: str = Field(
        default="clamd",
        description="ClamAV daemon hostname (Docker service name)"
    )
    
    CLAMAV_PORT: int = Field(
        default=3310,
        description="ClamAV daemon TCP port"
    )
    
    CLAMAV_UNIX_SOCKET: Optional[str] = Field(
        default=None,
        description="ClamAV Unix socket path (preferred over TCP)"
    )
    
    CLAMAV_TIMEOUT_CONNECT: float = Field(
        default=10.0,
        description="ClamAV connection timeout in seconds"
    )
    
    CLAMAV_TIMEOUT_SCAN: float = Field(
        default=60.0,
        description="ClamAV scan timeout in seconds"
    )
    
    CLAMAV_MAX_CONCURRENT_SCANS: int = Field(
        default=3,
        description="Maximum concurrent ClamAV scans to protect resources"
    )
    
    CLAMAV_FAIL_CLOSED: bool = Field(
        default=True,
        description="Fail-closed security policy: block uploads if ClamAV daemon is unreachable"
    )
    
    # ===================================================================
    # FREECAD & APPLICATION SPECIFIC
    # ===================================================================
    
    FREECADCMD_PATH: Optional[str] = Field(default=None, description="FreeCAD binary path")
    FREECAD_TIMEOUT_SECONDS: int = Field(default=1200, description="FreeCAD timeout")
    FREECAD_MONITORING_INTERVAL_SECONDS: float = Field(default=1.0, description="FreeCAD process monitoring interval in seconds")
    FREECAD_CIRCUIT_BREAKER_THRESHOLD: int = Field(default=5, description="Number of failures before circuit opens")
    FREECAD_CIRCUIT_BREAKER_RECOVERY_TIMEOUT: int = Field(default=60, description="Seconds to wait before attempting recovery")
    FREECAD_MAX_WORKERS: int = Field(default=4, description="Maximum concurrent FreeCAD operations")
    
    # ===================================================================
    # RABBITMQ & CELERY CONFIGURATION
    # ===================================================================
    
    RABBITMQ_URL: str = Field(
        default="amqp://freecad:freecad@rabbitmq:5672/",
        description="RabbitMQ connection URL"
    )
    
    CELERY_TASK_ALWAYS_EAGER: bool = Field(default=False, description="Celery eager mode")
    CELERY_WORKER_PREFETCH_MULTIPLIER: int = Field(default=1, description="Celery prefetch")
    
    # ===================================================================
    # DEVELOPMENT MODE FEATURES (Task 3.12)
    # ===================================================================
    
    DEV_AUTH_BYPASS: bool = Field(
        default=False,
        description="Bypass authentication in dev mode (DANGEROUS - dev only)"
    )
    
    DEV_DETAILED_ERRORS: bool = Field(
        default=False,
        description="Show detailed error traces in dev mode"
    )
    
    DEV_RESPONSE_ANNOTATIONS: bool = Field(
        default=False,
        description="Annotate API responses with dev info"
    )
    
    DEV_MOCK_EXTERNAL_SERVICES: bool = Field(
        default=False,
        description="Mock external services in dev mode"
    )
    
    # ===================================================================
    # PRODUCTION HARDENING FEATURES (Task 3.12)
    # ===================================================================
    
    PROD_FORCE_HTTPS: bool = Field(
        default=True,
        description="Force HTTPS redirects in production"
    )
    
    PROD_MASK_ERROR_DETAILS: bool = Field(
        default=True,
        description="Mask detailed error messages in production"
    )
    
    PROD_STRICT_COOKIES: bool = Field(
        default=True,
        description="Enforce strict cookie security in production"
    )
    
    PROD_DISABLE_DEBUG_ENDPOINTS: bool = Field(
        default=True,
        description="Disable debug endpoints in production"
    )
    
    # ===================================================================
    # MONITORING & OBSERVABILITY
    # ===================================================================
    
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = Field(
        default=None,
        description="OpenTelemetry collector endpoint"
    )
    
    OTEL_SERVICE_NAME: str = Field(
        default="freecad-ultra-enterprise",
        description="Service name for tracing"
    )
    
    SENTRY_DSN: Optional[str] = Field(default=None, description="Sentry DSN")
    
    # ===================================================================
    # FIELD VALIDATORS (DATA PARSING)
    # ===================================================================
    
    @field_validator('CORS_ALLOWED_ORIGINS', 'CORS_ALLOWED_METHODS', 'CORS_ALLOWED_HEADERS', 'CORS_EXPOSE_HEADERS', mode='after')
    @classmethod
    def normalize_cors_lists(cls, v):
        """Normalize CORS fields to always return lists."""
        if isinstance(v, str):
            # Handle single values and comma-separated values
            if ',' in v:
                return [item.strip() for item in v.split(',') if item.strip()]
            else:
                # Single value
                return [v.strip()] if v.strip() else []
        elif isinstance(v, list):
            return v
        return v if v is not None else []
    
    # ===================================================================
    # MODEL VALIDATORS (CRITICAL SECURITY)
    # ===================================================================
    
    @model_validator(mode='after')
    def validate_environment_security_settings(self) -> 'UltraEnterpriseEnvironment':
        """
        CRITICAL SECURITY VALIDATOR - Task 3.12 Implementation
        
        Validates environment-specific security configurations and enforces
        production hardening requirements with Turkish KVKV compliance.
        
        **Security Controls**:
        - Production environment security enforcement
        - Dev-mode safety checks
        - HTTPS and cookie security validation
        - CSRF and authentication configuration
        - Turkish data protection compliance
        """
        env_mode = self.ENV
        
        # Auto-determine dev mode based on environment
        if env_mode == EnvironmentMode.DEVELOPMENT:
            if self.DEV_MODE is None:
                self.DEV_MODE = True
        else:
            # Never allow dev mode in non-development environments
            if self.DEV_MODE:
                raise ValueError(
                    f"CRITICAL SECURITY VIOLATION: DEV_MODE cannot be enabled in {env_mode} environment. "
                    "Dev mode is only allowed in development environment for security reasons."
                )
        
        # Production environment security enforcement
        if env_mode == EnvironmentMode.PRODUCTION:
            
            # Validate production hardening is enabled
            if not self.PRODUCTION_HARDENING_ENABLED:
                raise ValueError(
                    "PRODUCTION SECURITY VIOLATION: PRODUCTION_HARDENING_ENABLED must be True "
                    "in production environment for banking-level security compliance."
                )
            
            # Validate secret keys are not default values
            if self.SECRET_KEY == "dev-secret-key-change-in-production-minimum-32-chars":
                raise ValueError(
                    "PRODUCTION SECURITY VIOLATION: SECRET_KEY must be changed from default "
                    "value in production environment. Use a cryptographically secure key."
                )
            
            if self.CSRF_SECRET_KEY == "dev-csrf-hmac-key-ultra-secure-banking-grade-change-in-production":
                raise ValueError(
                    "PRODUCTION SECURITY VIOLATION: CSRF_SECRET_KEY must be changed from "
                    "default value in production environment."
                )
            
            # Validate secret key lengths
            if len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "PRODUCTION SECURITY VIOLATION: SECRET_KEY must be at least 32 characters "
                    "long for sufficient cryptographic strength."
                )
            
            if len(self.CSRF_SECRET_KEY) < 32:
                raise ValueError(
                    "PRODUCTION SECURITY VIOLATION: CSRF_SECRET_KEY must be at least 32 "
                    "characters long for sufficient cryptographic strength."
                )
            
            # Validate CORS configuration
            cors_origins = self.CORS_ALLOWED_ORIGINS
            if cors_origins and "*" in cors_origins:
                raise ValueError(
                    "CRITICAL SECURITY VIOLATION: Wildcard '*' in CORS_ALLOWED_ORIGINS "
                    "is not allowed in production. Specify exact domains for security."
                )
            
            # Validate authentication bypass is disabled
            if self.DEV_AUTH_BYPASS:
                raise ValueError(
                    "CRITICAL SECURITY VIOLATION: DEV_AUTH_BYPASS must be False in production "
                    "environment. Authentication bypass creates severe security vulnerability."
                )
            
            # Validate debug features are disabled
            if self.DEBUG:
                warnings.warn(
                    "PRODUCTION WARNING: DEBUG mode is enabled in production environment. "
                    "This may expose sensitive information in error traces.",
                    UserWarning
                )
            
            if self.DEV_DETAILED_ERRORS:
                raise ValueError(
                    "PRODUCTION SECURITY VIOLATION: DEV_DETAILED_ERRORS must be False in "
                    "production to prevent information disclosure."
                )
            
            # Auto-configure secure cookies in production
            if self.SESSION_COOKIE_SECURE is None:
                self.SESSION_COOKIE_SECURE = True
            elif not self.SESSION_COOKIE_SECURE:
                raise ValueError(
                    "PRODUCTION SECURITY VIOLATION: SESSION_COOKIE_SECURE must be True in "
                    "production to ensure cookies are only sent over HTTPS."
                )
        
        # Development environment configuration
        elif env_mode == EnvironmentMode.DEVELOPMENT:
            
            # Auto-configure development settings
            if self.SESSION_COOKIE_SECURE is None:
                self.SESSION_COOKIE_SECURE = False  # Allow HTTP in dev
            
            # Enable dev features if dev mode is on
            if self.DEV_MODE:
                # Log dev mode activation
                logger.info(
                    "DEVELOPMENT MODE ACTIVATED: Security guards relaxed for development",
                    extra={
                        'operation': 'dev_mode_activated',
                        'environment': env_mode,
                        'features': {
                            'auth_bypass': self.DEV_AUTH_BYPASS,
                            'detailed_errors': self.DEV_DETAILED_ERRORS,
                            'response_annotations': self.DEV_RESPONSE_ANNOTATIONS,
                            'csrf_localhost_bypass': self.CSRF_DEV_LOCALHOST_BYPASS
                        }
                    }
                )
        
        # Staging environment configuration
        elif env_mode == EnvironmentMode.STAGING:
            # Auto-configure staging settings (production-like but with some relaxation)
            if self.SESSION_COOKIE_SECURE is None:
                self.SESSION_COOKIE_SECURE = True
        
        # Validate Turkish KVKV compliance settings
        if self.KVKV_DATA_RETENTION_DAYS < 1:
            raise ValueError(
                "KVKV UYUMLULUK İHLALİ: Veri saklama süresi en az 1 gün olmalıdır "
                "(KVKV compliance violation: Data retention must be at least 1 day)."
            )
        
        if env_mode == EnvironmentMode.PRODUCTION:
            if not self.KVKV_AUDIT_LOG_ENABLED:
                raise ValueError(
                    "KVKV UYUMLULUK İHLALİ: Production ortamında denetim kayıtları zorunludur "
                    "(KVKV compliance violation: Audit logs required in production)."
                )
            
            if not self.AUDIT_HASH_CHAIN_ENABLED:
                raise ValueError(
                    "GÜVENLİK İHLALİ: Production ortamında denetim hash zinciri zorunludur "
                    "(Security violation: Audit hash chain required in production)."
                )
        
        return self
    
    @model_validator(mode='after')
    def validate_oauth_configuration(self) -> 'UltraEnterpriseEnvironment':
        """Validate OAuth2/OIDC configuration for Task 3.5 compliance."""
        
        if self.GOOGLE_OAUTH_ENABLED:
            if self.ENV == EnvironmentMode.PRODUCTION:
                if not self.GOOGLE_CLIENT_ID:
                    raise ValueError(
                        "OAUTH CONFIGURATION ERROR: GOOGLE_CLIENT_ID is required when "
                        "Google OAuth is enabled in production environment."
                    )
                
                if not self.GOOGLE_CLIENT_SECRET:
                    raise ValueError(
                        "OAUTH CONFIGURATION ERROR: GOOGLE_CLIENT_SECRET is required when "
                        "Google OAuth is enabled in production environment."
                    )
        
        return self
    
    # ===================================================================
    # COMPUTED PROPERTIES & HELPERS
    # ===================================================================
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.ENV == EnvironmentMode.DEVELOPMENT
    
    @property
    def is_staging(self) -> bool:
        """Check if running in staging mode."""
        return self.ENV == EnvironmentMode.STAGING
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.ENV == EnvironmentMode.PRODUCTION
    
    @property
    def is_dev_mode(self) -> bool:
        """Check if development mode features are enabled."""
        return self.DEV_MODE and self.is_development
    
    @property
    def should_force_https(self) -> bool:
        """Determine if HTTPS should be enforced."""
        return self.is_production and self.PROD_FORCE_HTTPS
    
    @property
    def should_mask_errors(self) -> bool:
        """Determine if error details should be masked."""
        return self.is_production and self.PROD_MASK_ERROR_DETAILS
    
    @property
    def should_use_secure_cookies(self) -> bool:
        """Determine if secure cookies should be used."""
        return self.SESSION_COOKIE_SECURE or False
    
    @property
    def environment_display_tr(self) -> str:
        """Turkish display for current environment."""
        displays = {
            EnvironmentMode.DEVELOPMENT: "Geliştirme Ortamı",
            EnvironmentMode.STAGING: "Test Ortamı", 
            EnvironmentMode.PRODUCTION: "Üretim Ortamı"
        }
        return displays.get(self.ENV, "Bilinmeyen Ortam")
    
    @property
    def security_level_display_tr(self) -> str:
        """Turkish display for security level."""
        if self.is_dev_mode:
            return "Güvenlik Seviyesi: Geliştirme (Gevşetilmiş Korumalar)"
        elif self.is_production:
            return "Güvenlik Seviyesi: Ultra-Kurumsal Bankacılık Düzeyi"
        elif self.is_staging:
            return "Güvenlik Seviyesi: Test Ortamı (Üretim Benzeri)"
        else:
            return "Güvenlik Seviyesi: Standart"
    
    @property
    def kvkv_compliance_status_tr(self) -> str:
        """Turkish display for KVKV compliance status."""
        if (self.KVKV_PII_MASKING_ENABLED and 
            self.KVKV_AUDIT_LOG_ENABLED and 
            self.KVKV_CONSENT_REQUIRED):
            return "KVKV Uyumluluğu: Tam Uyumlu ✓"
        else:
            return "KVKV Uyumluluğu: Eksik Yapılandırma ⚠"
    
    # Additional Turkish compatibility properties from legacy settings.py
    @property
    def cors_origins_display_tr(self) -> str:
        """Turkish display for CORS origins configuration"""
        return f"İzin verilen kaynaklar: {len(self.CORS_ALLOWED_ORIGINS)} kaynak"
    
    def get_environment_summary(self) -> Dict[str, Any]:
        """Get a summary of current environment configuration (sanitized)."""
        return {
            "environment": self.ENV,
            "dev_mode": self.is_dev_mode,
            "security_level": self.SECURITY_LEVEL,
            "production_hardening": self.PRODUCTION_HARDENING_ENABLED,
            "kvkv_compliance": self.KVKV_AUDIT_LOG_ENABLED,
            "features": {
                "csrf_protection": True,
                "rate_limiting": True,
                "audit_logging": self.AUDIT_LOG_ENABLED,
                "security_headers": self.SECURITY_CSP_ENABLED,
                "oauth_enabled": self.GOOGLE_OAUTH_ENABLED,
                "dev_auth_bypass": self.DEV_AUTH_BYPASS if self.is_development else False
            },
            "security_hardening": {
                "force_https": self.should_force_https,
                "secure_cookies": self.should_use_secure_cookies,
                "mask_errors": self.should_mask_errors,
                "hsts_enabled": self.SECURITY_HSTS_ENABLED
            }
        }


# Global environment configuration instance  
environment = UltraEnterpriseEnvironment()


def validate_startup_configuration() -> None:
    """
    Validate configuration at application startup.
    
    Performs comprehensive checks to ensure the environment is properly
    configured for the current deployment mode with Turkish KVKV compliance.
    """
    
    logger.info(
        "Validating ultra-enterprise environment configuration",
        extra={
            'operation': 'config_validation_start',
            'environment': environment.ENV,
            'dev_mode': environment.is_dev_mode
        }
    )
    
    # Check for critical misconfigurations
    warnings_found = []
    errors_found = []
    
    # Validate database connection
    if not environment.DATABASE_URL:
        errors_found.append("DATABASE_URL is required")
    
    # Validate Redis connection
    if not environment.REDIS_URL:
        errors_found.append("REDIS_URL is required")
    
    # Production-specific validations
    if environment.is_production:
        
        # Check for insecure production configurations
        if environment.DEBUG:
            warnings_found.append(
                "DEBUG mode enabled in production - may expose sensitive data"
            )
        
        # Validate OAuth configuration
        if environment.GOOGLE_OAUTH_ENABLED:
            if not environment.GOOGLE_CLIENT_ID:
                errors_found.append("GOOGLE_CLIENT_ID required for OAuth in production")
            if not environment.GOOGLE_CLIENT_SECRET:
                errors_found.append("GOOGLE_CLIENT_SECRET required for OAuth in production")
        
        # Check HTTPS enforcement
        if not environment.should_force_https:
            warnings_found.append(
                "HTTPS enforcement disabled in production - security risk"
            )
    
    # Log warnings
    for warning in warnings_found:
        logger.warning(
            f"Configuration warning: {warning}",
            extra={
                'operation': 'config_warning_detected',
                'warning': warning,
                'environment': environment.ENV
            }
        )
    
    # Log errors and potentially refuse to start
    for error in errors_found:
        logger.error(
            f"Configuration error: {error}",
            extra={
                'operation': 'config_error_detected',
                'error': error,
                'environment': environment.ENV
            }
        )
    
    if errors_found:
        raise RuntimeError(
            f"Critical configuration errors found: {', '.join(errors_found)}. "
            "Application cannot start with invalid configuration."
        )
    
    # Log successful validation
    logger.info(
        "Environment configuration validation completed successfully",
        extra={
            'operation': 'config_validation_complete',
            'environment': environment.ENV,
            'warnings_count': len(warnings_found),
            'summary': environment.get_environment_summary()
        }
    )


def log_environment_startup() -> None:
    """
    Log environment configuration at startup (sanitized for security).
    
    Logs configuration summary without sensitive information for audit trails.
    Implements Task 3.11 audit logging requirements.
    """
    
    summary = environment.get_environment_summary()
    
    logger.info(
        "Ultra-Enterprise environment configuration loaded",
        extra={
            'operation': 'config_loaded',
            'environment': environment.ENV,
            'config_summary': summary,
            'turkish_status': {
                'environment': environment.environment_display_tr,
                'security_level': environment.security_level_display_tr,
                'kvkv_compliance': environment.kvkv_compliance_status_tr
            }
        }
    )
    
    # Log security event if insecure configuration detected in production
    if environment.is_production and (environment.DEBUG or not environment.should_force_https):
        logger.warning(
            "Insecure configuration detected in production environment",
            extra={
                'operation': 'insecure_config_detected',
                'environment': environment.ENV,
                'issues': {
                    'debug_enabled': environment.DEBUG,
                    'https_not_enforced': not environment.should_force_https
                },
                'turkish_message': 'Üretim ortamında güvensiz yapılandırma tespit edildi'
            }
        )