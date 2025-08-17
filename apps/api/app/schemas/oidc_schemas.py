"""
OIDC Authentication Schemas for Task 3.5 - Google OAuth2/OIDC Integration

These schemas provide Pydantic validation for OIDC authentication endpoints
with ultra enterprise security standards and Turkish localization.
"""

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, EmailStr, validator


class OIDCAuthStartResponse(BaseModel):
    """Response schema for OIDC authentication start endpoint."""
    
    authorization_url: str = Field(
        ...,
        description="Google OAuth2 authorization URL with PKCE parameters",
        example="https://accounts.google.com/o/oauth2/auth?client_id=..."
    )
    
    state: str = Field(
        ...,
        description="OAuth2 state parameter for CSRF protection",
        min_length=32,
        max_length=256
    )
    
    expires_in: int = Field(
        default=900,
        description="State expiration time in seconds (15 minutes)",
        ge=300,
        le=1800
    )
    
    message: str = Field(
        default="OIDC kimlik doğrulama başlatıldı",
        description="Turkish success message"
    )


class OIDCCallbackRequest(BaseModel):
    """Request schema for OIDC callback endpoint."""
    
    code: str = Field(
        ...,
        description="Authorization code from Google",
        min_length=10,
        max_length=2048
    )
    
    state: str = Field(
        ...,
        description="OAuth2 state parameter for validation",
        min_length=32,
        max_length=256
    )
    
    @validator('code')
    def validate_code(cls, v):
        """Validate authorization code format."""
        if not v or not v.strip():
            raise ValueError("Yetkilendirme kodu geçersiz")
        return v.strip()
    
    @validator('state')
    def validate_state(cls, v):
        """Validate state parameter format."""
        if not v or not v.strip():
            raise ValueError("State parametresi geçersiz")
        return v.strip()


class OIDCUserProfile(BaseModel):
    """OIDC user profile information from provider."""
    
    sub: str = Field(
        ...,
        description="OIDC subject identifier",
        min_length=1,
        max_length=255
    )
    
    email: EmailStr = Field(
        ...,
        description="Email address from OIDC provider"
    )
    
    email_verified: bool = Field(
        default=False,
        description="Whether email is verified by provider"
    )
    
    name: Optional[str] = Field(
        None,
        description="Full name from OIDC provider",
        max_length=255
    )
    
    picture: Optional[str] = Field(
        None,
        description="Profile picture URL",
        max_length=500
    )
    
    locale: Optional[str] = Field(
        None,
        description="User locale from provider",
        max_length=10
    )


class OIDCAuthResponse(BaseModel):
    """Response schema for successful OIDC authentication."""
    
    access_token: str = Field(
        ...,
        description="JWT access token for API requests",
        min_length=10
    )
    
    token_type: str = Field(
        default="bearer",
        description="Token type (always bearer)"
    )
    
    expires_in: int = Field(
        ...,
        description="Access token expiration time in seconds",
        ge=300,
        le=86400
    )
    
    user_id: int = Field(
        ...,
        description="Local user ID",
        ge=1
    )
    
    email: EmailStr = Field(
        ...,
        description="User email address"
    )
    
    full_name: Optional[str] = Field(
        None,
        description="User full name",
        max_length=255
    )
    
    role: str = Field(
        ...,
        description="User role",
        pattern="^(admin|engineer|operator|viewer)$"
    )
    
    is_new_user: bool = Field(
        default=False,
        description="Whether this is a newly created user account"
    )
    
    is_new_oidc_link: bool = Field(
        default=False,
        description="Whether this is a new OIDC account linkage"
    )
    
    profile: OIDCUserProfile = Field(
        ...,
        description="OIDC profile information"
    )
    
    message: str = Field(
        default="OIDC girişi başarılı",
        description="Turkish success message"
    )


class OIDCErrorResponse(BaseModel):
    """Error response schema for OIDC authentication failures."""
    
    error_code: str = Field(
        ...,
        description="Standardized error code",
        pattern="^ERR-OIDC-[A-Z-]+$",
        example="ERR-OIDC-STATE"
    )
    
    message: str = Field(
        ...,
        description="Human-readable Turkish error message",
        min_length=10,
        max_length=500,
        example="OIDC state doğrulaması başarısız"
    )
    
    details: Optional[Dict[str, Any]] = Field(
        None,
        description="Additional error details (sanitized)"
    )
    
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="Error timestamp"
    )
    
    help_url: Optional[str] = Field(
        None,
        description="Help documentation URL",
        example="https://docs.example.com/auth/oidc-errors"
    )


class OIDCAccountInfo(BaseModel):
    """OIDC account information schema."""
    
    id: str = Field(
        ...,
        description="OIDC account UUID",
        pattern="^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
    )
    
    provider: str = Field(
        ...,
        description="OIDC provider name",
        example="google"
    )
    
    email: EmailStr = Field(
        ...,
        description="Email from OIDC provider"
    )
    
    email_verified: bool = Field(
        ...,
        description="Email verification status"
    )
    
    picture: Optional[str] = Field(
        None,
        description="Profile picture URL"
    )
    
    first_login_at: Optional[datetime] = Field(
        None,
        description="First login timestamp"
    )
    
    last_login_at: Optional[datetime] = Field(
        None,
        description="Last login timestamp"
    )
    
    login_count: int = Field(
        ...,
        description="Total login count",
        ge=0
    )
    
    is_active: bool = Field(
        ...,
        description="Account active status"
    )
    
    created_at: datetime = Field(
        ...,
        description="Account creation timestamp"
    )


class OIDCStatusResponse(BaseModel):
    """Response schema for OIDC status/configuration endpoint."""
    
    google_oauth_enabled: bool = Field(
        ...,
        description="Whether Google OAuth is enabled"
    )
    
    client_id: Optional[str] = Field(
        None,
        description="Google OAuth client ID (public information)",
        example="123456789-abcdef.apps.googleusercontent.com"
    )
    
    scopes: list[str] = Field(
        default=["openid", "email", "profile"],
        description="OAuth scopes requested"
    )
    
    redirect_uri: Optional[str] = Field(
        None,
        description="OAuth redirect URI for this environment"
    )
    
    discovery_url: str = Field(
        default="https://accounts.google.com/.well-known/openid-configuration",
        description="Google OIDC discovery URL"
    )


# Error code constants for OIDC operations
OIDC_ERROR_CODES = {
    'ERR-OIDC-STATE': 'OIDC state doğrulaması başarısız',
    'ERR-OIDC-NONCE': 'OIDC nonce doğrulaması başarısız',
    'ERR-OIDC-TOKEN-EXCHANGE': 'OIDC token değişimi başarısız',
    'ERR-OIDC-EMAIL-CONFLICT': 'Email adresi başka bir hesapla ilişkili',
    'ERR-OIDC-CONFIG-FAILED': 'OIDC yapılandırması alınamadı',
    'ERR-OIDC-AUTH-URL-FAILED': 'OIDC yetkilendirme URL\'si oluşturulamadı',
    'ERR-OIDC-REDIRECT-MISMATCH': 'OIDC redirect URI uyumsuzluğu',
    'ERR-OIDC-PKCE-MISSING': 'OIDC PKCE doğrulayıcısı bulunamadı',
    'ERR-OIDC-TOKEN-INVALID': 'OIDC token geçersiz',
    'ERR-OIDC-TOKEN-EXPIRED': 'OIDC token süresi dolmuş',
    'ERR-OIDC-INVALID-ISSUER': 'OIDC issuer geçersiz',
    'ERR-OIDC-INVALID-AUDIENCE': 'OIDC audience geçersiz',
    'ERR-OIDC-NO-ID-TOKEN': 'OIDC ID token bulunamadı',
    'ERR-OIDC-EMAIL-NOT-VERIFIED': 'E-posta adresi doğrulanmamış',
    'ERR-OIDC-ACCOUNT-INACTIVE': 'Kullanıcı hesabı aktif değil',
    'ERR-OIDC-AUTH-FAILED': 'OIDC kimlik doğrulama başarısız',
    'ERR-OIDC-USER-CREATION-FAILED': 'OIDC kullanıcı hesabı oluşturulamadı',
    'ERR-OIDC-STATE-CORRUPT': 'OIDC state verisi bozuk',
    'ERR-OIDC-STATE-VALIDATION-FAILED': 'OIDC state doğrulaması başarısız',
    'ERR-OIDC-TOKEN-EXCHANGE-FAILED': 'OIDC token değişimi başarısız',
    'ERR-OIDC-CONFIG-UNEXPECTED': 'OIDC yapılandırması beklenmeyen hata',
    'ERR-OIDC-DISABLED': 'OIDC kimlik doğrulama devre dışı'
}


def create_oidc_error_response(
    error_code: str,
    details: Optional[Dict[str, Any]] = None
) -> OIDCErrorResponse:
    """
    Create standardized OIDC error response.
    
    Args:
        error_code: Error code from OIDC_ERROR_CODES
        details: Additional error details
        
    Returns:
        OIDCErrorResponse with Turkish message
    """
    message = OIDC_ERROR_CODES.get(error_code, 'Bilinmeyen OIDC hatası')
    
    return OIDCErrorResponse(
        error_code=error_code,
        message=message,
        details=details
    )