"""
Ultra-Enterprise Security Settings Configuration
Implements banking-level security standards with Turkish KVKV compliance
"""

from __future__ import annotations

from typing import List, Dict, Optional, Any
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class UltraEnterpriseSettings(BaseSettings):
    """
    Ultra-Enterprise Security Configuration with Turkish KVKV Compliance
    
    **Risk Assessment**: CRITICAL - Contains production security configurations
    **Compliance**: KVKV Article 10, GDPR Article 25, ISO 27001
    **Security Level**: Banking-Grade
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
        env_prefix="",
    )
    
    # Environment Configuration
    ENV: str = Field(
        default="development", 
        description="Environment: development, staging, production"
    )
    
    # CORS Security Configuration - CRITICAL SECURITY SECTION
    CORS_ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000"],
        description="List of allowed CORS origins. NEVER use '*' in production for security"
    )
    
    CORS_ALLOWED_METHODS: List[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        description="List of allowed HTTP methods for CORS"
    )
    
    CORS_ALLOWED_HEADERS: List[str] = Field(
        default=["Accept", "Accept-Language", "Content-Language", "Content-Type", "Authorization", "X-Requested-With", "X-CSRF-Token"],
        description="List of allowed headers for CORS requests"
    )
    
    CORS_EXPOSE_HEADERS: List[str] = Field(
        default=["X-Total-Count", "X-Page-Count", "X-Request-ID"],
        description="Headers exposed to the browser in CORS responses"
    )
    
    CORS_ALLOW_CREDENTIALS: bool = Field(
        default=True,
        description="Allow credentials in CORS requests (required for authenticated requests)"
    )
    
    CORS_MAX_AGE: int = Field(
        default=3600,
        description="Maximum age in seconds for CORS preflight cache"
    )
    
    # Security Headers Configuration
    SECURITY_HSTS_MAX_AGE: int = Field(
        default=31536000,  # 1 year
        description="HSTS max-age in seconds"
    )
    
    SECURITY_CSP_REPORT_URI: Optional[str] = Field(
        default=None,
        description="Content Security Policy report URI for violation reports"
    )
    
    # Rate Limiting Configuration
    RATE_LIMIT_GLOBAL: str = Field(
        default="1000/hour",
        description="Global rate limit across all endpoints"
    )
    
    RATE_LIMIT_AUTH: str = Field(
        default="10/minute",
        description="Rate limit for authentication endpoints"
    )
    
    RATE_LIMIT_API: str = Field(
        default="300/hour",
        description="Rate limit for API endpoints"
    )
    
    # Brute Force Protection Configuration
    BRUTE_FORCE_MAX_ATTEMPTS: int = Field(
        default=5,
        description="Maximum failed login attempts before account lockout"
    )
    
    BRUTE_FORCE_LOCKOUT_DURATION: int = Field(
        default=900,  # 15 minutes
        description="Account lockout duration in seconds after brute force detection"
    )
    
    BRUTE_FORCE_RESET_TIME: int = Field(
        default=3600,  # 1 hour
        description="Time to reset failed attempt counter"
    )
    
    # Turkish KVKV Compliance Configuration
    KVKV_DATA_RETENTION_DAYS: int = Field(
        default=2555,  # 7 years
        description="Data retention period for Turkish KVKV compliance"
    )
    
    KVKV_PII_MASKING_ENABLED: bool = Field(
        default=True,
        description="Enable PII masking for Turkish personal data protection"
    )
    
    KVKV_AUDIT_LOG_ENABLED: bool = Field(
        default=True,
        description="Enable audit logging for KVKV compliance"
    )
    
    # Enterprise Audit Configuration
    AUDIT_LOG_RETENTION_DAYS: int = Field(
        default=2555,  # 7 years for banking compliance
        description="Audit log retention period in days"
    )
    
    AUDIT_HASH_CHAIN_ENABLED: bool = Field(
        default=True,
        description="Enable cryptographic hash chain for audit integrity"
    )
    
    AUDIT_REAL_TIME_MONITORING: bool = Field(
        default=True,
        description="Enable real-time security event monitoring"
    )
    
    # Database Security Configuration
    DB_CONNECTION_POOL_SIZE: int = Field(
        default=20,
        description="Database connection pool size"
    )
    
    DB_CONNECTION_TIMEOUT: int = Field(
        default=30,
        description="Database connection timeout in seconds"
    )
    
    DB_QUERY_TIMEOUT: int = Field(
        default=60,
        description="Database query timeout in seconds"
    )
    
    # Session Security Configuration
    SESSION_TIMEOUT_MINUTES: int = Field(
        default=30,
        description="Session timeout in minutes"
    )
    
    SESSION_ABSOLUTE_TIMEOUT_MINUTES: int = Field(
        default=480,  # 8 hours
        description="Absolute session timeout in minutes"
    )
    
    SESSION_COOKIE_SECURE: bool = Field(
        default=True,
        description="Use secure cookies for sessions (HTTPS only)"
    )
    
    SESSION_COOKIE_HTTPONLY: bool = Field(
        default=True,
        description="Use HTTP-only cookies to prevent XSS"
    )
    
    SESSION_COOKIE_SAMESITE: str = Field(
        default="strict",
        description="SameSite cookie attribute for CSRF protection"
    )
    
    # CSRF Protection Configuration (Task 3.8)
    CSRF_SECRET_KEY: str = Field(
        default="dev-csrf-hmac-key-ultra-secure-banking-grade-change-in-production",
        description="Secret key for CSRF token HMAC generation (MUST be changed in production)"
    )
    
    CSRF_TOKEN_LIFETIME_SECONDS: int = Field(
        default=7200,  # 2 hours
        description="CSRF token lifetime in seconds"
    )
    
    CSRF_RATE_LIMIT_PER_MINUTE: int = Field(
        default=60,
        description="Maximum CSRF tokens per minute per IP address"
    )
    
    CSRF_REQUIRE_AUTH: bool = Field(
        default=True,
        description="Require authentication for CSRF protection"
    )
    
    @model_validator(mode='after')
    def validate_production_security_settings(self) -> 'UltraEnterpriseSettings':
        """
        CRITICAL SECURITY VALIDATOR
        
        Validates production security settings to prevent critical vulnerabilities.
        This fixes the Gemini Code Assist feedback about os.getenv("ENV") bug.
        
        **Security Issues Prevented**:
        - Wildcard CORS origins in production (CVE-2020-7791 equivalent)
        - Overly permissive headers in production
        - Insecure session configuration
        
        **Compliance**: Turkish KVKV, GDPR Article 25, ISO 27001
        """
        env = self.ENV
        
        # Fix Issue 1: Critical CORS Security Bug
        if env == "production":
            cors_origins = self.CORS_ALLOWED_ORIGINS
            if cors_origins and "*" in cors_origins:
                raise ValueError(
                    "CRITICAL SECURITY VIOLATION: Wildcard '*' in CORS_ALLOWED_ORIGINS "
                    "is not allowed in production environment. This creates a severe "
                    "security vulnerability allowing any domain to make requests. "
                    "Specify exact domains instead."
                )
            
            # Fix Issue 3: Prevent wildcard headers in production
            cors_headers = self.CORS_ALLOWED_HEADERS
            if cors_headers and "*" in cors_headers:
                raise ValueError(
                    "SECURITY VIOLATION: Wildcard '*' in CORS_ALLOWED_HEADERS "
                    "is overly permissive in production environment. "
                    "Specify exact headers for security."
                )
            
            cors_methods = self.CORS_ALLOWED_METHODS
            if cors_methods and "*" in cors_methods:
                raise ValueError(
                    "SECURITY VIOLATION: Wildcard '*' in CORS_ALLOWED_METHODS "
                    "is overly permissive in production environment. "
                    "Specify exact methods for security."
                )
            
            # Validate session security in production
            if not self.SESSION_COOKIE_SECURE:
                raise ValueError(
                    "SECURITY VIOLATION: SESSION_COOKIE_SECURE must be True in production "
                    "to ensure cookies are only sent over HTTPS."
                )
            
            if not self.SESSION_COOKIE_HTTPONLY:
                raise ValueError(
                    "SECURITY VIOLATION: SESSION_COOKIE_HTTPONLY must be True in production "
                    "to prevent XSS attacks on session cookies."
                )
            
            # Validate CSRF protection configuration
            if self.CSRF_SECRET_KEY == "dev-csrf-hmac-key-ultra-secure-banking-grade-change-in-production":
                raise ValueError(
                    "SECURITY VIOLATION: CSRF_SECRET_KEY must be changed from default value "
                    "in production environment. Use a cryptographically secure random key."
                )
            
            if len(self.CSRF_SECRET_KEY) < 32:
                raise ValueError(
                    "SECURITY VIOLATION: CSRF_SECRET_KEY must be at least 32 characters long "
                    "for sufficient cryptographic strength in production."
                )
        
        # Validate Turkish KVKV compliance settings
        if self.KVKV_DATA_RETENTION_DAYS < 1:
            raise ValueError(
                "KVKV COMPLIANCE VIOLATION: Data retention period must be at least 1 day "
                "for Turkish data protection compliance."
            )
        
        # Validate audit configuration
        if env == "production":
            if not self.AUDIT_LOG_RETENTION_DAYS:
                raise ValueError(
                    "AUDIT COMPLIANCE VIOLATION: Audit log retention must be configured "
                    "for production environments to meet regulatory requirements."
                )
            
            if not self.AUDIT_HASH_CHAIN_ENABLED:
                raise ValueError(
                    "SECURITY VIOLATION: Audit hash chain must be enabled in production "
                    "to ensure audit log integrity and prevent tampering."
                )
        
        return self
    
    @model_validator(mode='after')
    def validate_rate_limiting_configuration(self) -> 'UltraEnterpriseSettings':
        """
        Validate rate limiting configuration for security
        
        Ensures rate limits are properly configured to prevent DoS attacks
        and brute force attempts while maintaining system usability.
        """
        env = self.ENV
        
        if env == "production":
            # Validate brute force protection
            max_attempts = self.BRUTE_FORCE_MAX_ATTEMPTS
            if max_attempts < 3 or max_attempts > 10:
                raise ValueError(
                    "SECURITY CONFIGURATION: BRUTE_FORCE_MAX_ATTEMPTS should be "
                    "between 3 and 10 attempts for optimal security vs usability."
                )
            
            lockout_duration = self.BRUTE_FORCE_LOCKOUT_DURATION
            if lockout_duration < 300:  # 5 minutes minimum
                raise ValueError(
                    "SECURITY CONFIGURATION: BRUTE_FORCE_LOCKOUT_DURATION should be "
                    "at least 300 seconds (5 minutes) for effective protection."
                )
        
        return self
    
    # Turkish Localization Properties
    @property
    def cors_origins_display_tr(self) -> str:
        """Turkish display for CORS origins configuration"""
        return f"İzin verilen kaynaklar: {len(self.CORS_ALLOWED_ORIGINS)} kaynak"
    
    @property
    def security_level_tr(self) -> str:
        """Turkish display for security level"""
        if self.ENV == "production":
            return "Güvenlik Seviyesi: Ultra-Kurumsal Bankacılık Düzeyi"
        elif self.ENV == "staging":
            return "Güvenlik Seviyesi: Test Ortamı"
        else:
            return "Güvenlik Seviyesi: Geliştirme Ortamı"
    
    @property
    def kvkv_compliance_status_tr(self) -> str:
        """Turkish display for KVKV compliance status"""
        if self.KVKV_PII_MASKING_ENABLED and self.KVKV_AUDIT_LOG_ENABLED:
            return "KVKV Uyumluluğu: Tam Uyumlu ✓"
        else:
            return "KVKV Uyumluluğu: Eksik Yapılandırma ⚠"


# Global settings instance
ultra_enterprise_settings = UltraEnterpriseSettings()