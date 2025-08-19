"""
Magic Link schemas for Task 3.6 ultra enterprise passwordless authentication.

These schemas define the API contracts for magic link endpoints with:
- Strict validation and Turkish error messages
- Email enumeration protection patterns
- Device fingerprint security tracking
- Enterprise audit trail support
"""

from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field, validator


class MagicLinkRequestRequest(BaseModel):
    """Magic link request schema."""

    email: EmailStr = Field(
        ..., description="Magic link gönderilecek e-posta adresi", example="kullanici@example.com"
    )

    device_fingerprint: Optional[str] = Field(
        None, max_length=512, description="Cihaz parmak izi (güvenlik için)", example="fp_abc123..."
    )

    @validator("email")
    def validate_email(cls, v):
        """Validate and normalize email."""
        return v.lower().strip()


class MagicLinkRequestResponse(BaseModel):
    """Magic link request response schema (always success for security)."""

    message: str = Field(
        default="Magic link e-posta adresinize gönderildi. Gelen kutunuzu kontrol edin.",
        description="Başarı mesajı (her zaman aynı güvenlik için)",
    )

    expires_in_minutes: int = Field(default=15, description="Magic link geçerlilik süresi (dakika)")


class MagicLinkConsumeRequest(BaseModel):
    """Magic link consumption request schema."""

    token: str = Field(
        ...,
        min_length=10,
        max_length=512,
        description="Magic link token'ı",
        example="eyJ0eXAiOiJKV1QiLCJhbGc...",
    )

    device_fingerprint: Optional[str] = Field(
        None,
        max_length=512,
        description="Cihaz parmak izi (güvenlik doğrulaması için)",
        example="fp_abc123...",
    )


class MagicLinkConsumeResponse(BaseModel):
    """Magic link consumption response schema."""

    access_token: str = Field(..., description="JWT erişim token'ı")
    token_type: str = Field(default="bearer", description="Token türü")
    expires_in: int = Field(..., description="Token geçerlilik süresi (saniye)")

    user_id: int = Field(..., description="Kullanıcı ID'si")
    email: str = Field(..., description="Kullanıcı e-posta adresi")
    full_name: Optional[str] = Field(None, description="Kullanıcı tam adı")
    role: str = Field(..., description="Kullanıcı rolü")

    session_id: str = Field(..., description="Oturum ID'si")

    # Additional security information
    login_method: str = Field(default="magic_link", description="Giriş yöntemi")

    password_must_change: Optional[bool] = Field(None, description="Şifre değiştirilmeli mi?")


class MagicLinkErrorResponse(BaseModel):
    """Magic link error response schema."""

    error_code: str = Field(..., description="Magic link hata kodu", example="ERR-ML-EXPIRED")
    message: str = Field(..., description="Hata mesajı", example="Magic link süresi dolmuş")
    details: Optional[Dict[str, Any]] = Field(None, description="Ek hata detayları")


class MagicLinkStatusResponse(BaseModel):
    """Magic link status response schema (for admin/debugging)."""

    magic_link_id: str = Field(..., description="Magic link ID'si")
    email_hash: int = Field(..., description="E-posta hash'i (maskelenmiş)")
    issued_at: datetime = Field(..., description="Oluşturulma zamanı")
    consumed_at: Optional[datetime] = Field(None, description="Kullanılma zamanı")
    is_expired: bool = Field(..., description="Süresi dolmuş mu?")
    is_consumed: bool = Field(..., description="Kullanılmış mı?")
    is_valid: bool = Field(..., description="Geçerli mi?")
    consumption_attempts: int = Field(..., description="Kullanım deneme sayısı")
    remaining_seconds: int = Field(..., description="Kalan süre (saniye)")


# Magic link error code mappings for consistent error responses
MAGIC_LINK_ERROR_CODES = {
    "ERR-ML-MALFORMED": "Magic link formatı geçersiz",
    "ERR-ML-INVALID": "Magic link geçersiz",
    "ERR-ML-EXPIRED": "Magic link süresi dolmuş",
    "ERR-ML-ALREADY-USED": "Magic link zaten kullanılmış",
    "ERR-ML-USER-NOT-FOUND": "Kullanıcı bulunamadı",
    "ERR-ML-ACCOUNT-LOCKED": "Hesap kilitli veya aktif değil",
    "ERR-ML-RATE-LIMITED": "Çok fazla magic link talebi",
    "ERR-ML-CONSUMPTION-FAILED": "Magic link kullanımı başarısız",
    "ERR-ML-REQUEST-FAILED": "Magic link talebi başarısız",
    "ERR-ML-SYSTEM-ERROR": "Magic link sistem hatası",
}
