"""
Ultra-Enterprise Configuration Management System
===============================================

Centralized configuration management with environment-based settings
for CORS, security, and production deployment settings.

Turkish KVKV Compliance Features:
- Configurable CORS origins for Turkish regulatory requirements
- Security headers management for banking-level compliance
- Environment-specific configuration validation

Security Features:
- Production-ready CORS configuration
- Secure defaults with explicit overrides
- Validation for critical security settings
"""

import os
from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import Field, validator


class UltraEnterpriseSettings(BaseSettings):
    """Ultra-enterprise settings with Turkish KVKV compliance."""
    
    # Environment
    ENV: str = Field(default="development", description="Environment: development, staging, production")
    
    # CORS Configuration
    CORS_ALLOWED_ORIGINS: str = Field(
        default="http://localhost:3000",
        description="Comma-separated list of allowed origins"
    )
    CORS_ALLOW_CREDENTIALS: bool = Field(
        default=True,
        description="Allow credentials in CORS requests"
    )
    CORS_ALLOWED_METHODS: str = Field(
        default="GET,POST,PUT,DELETE,PATCH,OPTIONS",
        description="Comma-separated list of allowed HTTP methods"
    )
    CORS_ALLOWED_HEADERS: str = Field(
        default="*",
        description="Comma-separated list of allowed headers or '*' for all"
    )
    CORS_EXPOSE_HEADERS: str = Field(
        default="X-Correlation-ID,X-Session-ID,X-KVKV-Compliant,X-Rate-Limit-Remaining,X-Rate-Limit-Reset",
        description="Comma-separated list of headers to expose"
    )
    CORS_MAX_AGE: int = Field(
        default=600,
        description="Maximum age for preflight cache in seconds"
    )
    
    # Security Configuration
    SECURITY_ENVIRONMENT: str = Field(
        default="development", 
        description="Security environment level"
    )
    SECURITY_CSP_ENABLED: bool = Field(
        default=True,
        description="Enable Content Security Policy headers"
    )
    SECURITY_HSTS_ENABLED: bool = Field(
        default=True,
        description="Enable HTTP Strict Transport Security"
    )
    
    # Frontend Configuration
    NEXT_PUBLIC_API_BASE_URL: str = Field(
        default="http://localhost:8000",
        description="Frontend API base URL"
    )
    
    @validator('ENV')
    def validate_environment(cls, v):
        """Validate environment value."""
        allowed_envs = ["development", "staging", "production"]
        if v not in allowed_envs:
            raise ValueError(f"ENV must be one of {allowed_envs}")
        return v
    
    @validator('CORS_ALLOWED_ORIGINS', pre=True)
    def validate_cors_origins(cls, v):
        """Validate CORS origins for security."""
        if isinstance(v, str):
            origins = [origin.strip() for origin in v.split(',')]
            
            # Security check: warn about wildcard in production
            if "*" in origins and os.getenv("ENV") == "production":
                raise ValueError(
                    "Wildcard '*' in CORS_ALLOWED_ORIGINS is not allowed in production"
                )
                
            return origins
        return v
    
    @validator('CORS_ALLOWED_METHODS', pre=True) 
    def validate_cors_methods(cls, v):
        """Validate and parse CORS methods."""
        if isinstance(v, str):
            methods = [method.strip().upper() for method in v.split(',')]
            
            # Validate HTTP methods
            allowed_methods = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"]
            invalid_methods = [m for m in methods if m not in allowed_methods]
            if invalid_methods:
                raise ValueError(f"Invalid HTTP methods: {invalid_methods}")
                
            return methods
        return v
    
    @validator('CORS_ALLOWED_HEADERS', pre=True)
    def validate_cors_headers(cls, v):
        """Validate and parse CORS headers."""
        if isinstance(v, str) and v != "*":
            return [header.strip() for header in v.split(',')]
        return v
    
    @validator('CORS_EXPOSE_HEADERS', pre=True)
    def validate_cors_expose_headers(cls, v):
        """Validate and parse CORS expose headers."""
        if isinstance(v, str):
            return [header.strip() for header in v.split(',')]
        return v
    
    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.ENV == "production"
    
    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.ENV == "development"
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Get CORS origins as a list."""
        if isinstance(self.CORS_ALLOWED_ORIGINS, list):
            return self.CORS_ALLOWED_ORIGINS
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(',')]
    
    @property
    def cors_methods_list(self) -> List[str]:
        """Get CORS methods as a list."""
        if isinstance(self.CORS_ALLOWED_METHODS, list):
            return self.CORS_ALLOWED_METHODS
        return [method.strip().upper() for method in self.CORS_ALLOWED_METHODS.split(',')]
    
    @property
    def cors_headers_list(self) -> List[str]:
        """Get CORS headers as a list."""
        if self.CORS_ALLOWED_HEADERS == "*":
            return ["*"]
        if isinstance(self.CORS_ALLOWED_HEADERS, list):
            return self.CORS_ALLOWED_HEADERS
        return [header.strip() for header in self.CORS_ALLOWED_HEADERS.split(',')]
    
    @property
    def cors_expose_headers_list(self) -> List[str]:
        """Get CORS expose headers as a list."""
        if isinstance(self.CORS_EXPOSE_HEADERS, list):
            return self.CORS_EXPOSE_HEADERS
        return [header.strip() for header in self.CORS_EXPOSE_HEADERS.split(',')]
    
    class Config:
        env_file = ".env"
        case_sensitive = True


# Global settings instance
settings = UltraEnterpriseSettings()


def get_settings() -> UltraEnterpriseSettings:
    """Get application settings instance.
    
    Returns:
        UltraEnterpriseSettings: Configured settings instance
    """
    return settings