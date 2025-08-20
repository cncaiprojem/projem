"""
Authentication schemas for Task 3.1 and 3.3 ultra enterprise authentication.
These schemas define the API contracts for authentication endpoints including JWT.
"""

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Field, validator, model_validator


class UserRegisterRequest(BaseModel):
    """User registration request schema."""
    
    email: EmailStr = Field(
        ...,
        description="Kullanıcı e-posta adresi",
        example="kullanici@example.com"
    )
    password: str = Field(
        ...,
        min_length=12,
        max_length=128,
        description="Kullanıcı şifresi (en az 12 karakter)",
        example="GüçlüŞifre123!"
    )
    full_name: Optional[str] = Field(
        None,
        min_length=2,
        max_length=255,
        description="Kullanıcının tam adı",
        example="Ahmet Yılmaz"
    )
    data_processing_consent: bool = Field(
        True,
        description="KVKK veri işleme rızası (zorunlu)"
    )
    marketing_consent: bool = Field(
        False,
        description="Pazarlama iletişimi rızası (isteğe bağlı)"
    )
    
    @validator('email')
    def validate_email(cls, v):
        """Validate and normalize email."""
        return v.lower().strip()
    
    @validator('full_name')
    def validate_full_name(cls, v):
        """Validate full name if provided."""
        if v:
            v = v.strip()
            if len(v) < 2:
                raise ValueError('Tam ad en az 2 karakter olmalıdır')
        return v
    
    @model_validator(mode='after')
    def validate_required_consent(self):
        """Ensure required KVKK consent is given."""
        if not self.data_processing_consent:
            raise ValueError('KVKK veri işleme rızası zorunludur')
        return self


class UserRegisterResponse(BaseModel):
    """User registration response schema."""
    
    user_id: int = Field(..., description="Oluşturulan kullanıcı ID'si")
    email: str = Field(..., description="Kullanıcı e-posta adresi")
    message: str = Field(
        default="Kayıt başarılı. E-posta doğrulama bağlantısı gönderildi.",
        description="Başarı mesajı"
    )


class UserLoginRequest(BaseModel):
    """User login request schema."""
    
    email: EmailStr = Field(
        ...,
        description="Kullanıcı e-posta adresi",
        example="kullanici@example.com"
    )
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Kullanıcı şifresi",
        example="GüçlüŞifre123!"
    )
    device_fingerprint: Optional[str] = Field(
        None,
        max_length=512,
        description="Cihaz parmak izi (güvenlik için)",
        example="fp_123abc..."
    )
    mfa_code: Optional[str] = Field(
        None,
        min_length=6,
        max_length=8,
        description="İki faktörlü doğrulama kodu (gerekirse)",
        example="123456"
    )
    
    @validator('email')
    def validate_email(cls, v):
        """Validate and normalize email."""
        return v.lower().strip()


class UserLoginResponse(BaseModel):
    """User login response schema."""
    
    access_token: str = Field(..., description="JWT erişim token'ı")
    token_type: str = Field(default="bearer", description="Token türü")
    expires_in: int = Field(..., description="Token geçerlilik süresi (saniye)")
    user_id: int = Field(..., description="Kullanıcı ID'si")
    email: str = Field(..., description="Kullanıcı e-posta adresi")
    full_name: Optional[str] = Field(None, description="Kullanıcı tam adı")
    role: str = Field(..., description="Kullanıcı rolü")
    mfa_required: Optional[bool] = Field(
        None,
        description="İki faktörlü doğrulama gerekli mi?"
    )
    password_must_change: Optional[bool] = Field(
        None,
        description="Şifre değiştirilmeli mi?"
    )


class PasswordStrengthRequest(BaseModel):
    """Password strength check request schema."""
    
    password: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="Kontrol edilecek şifre",
        example="TestŞifre123!"
    )


class PasswordStrengthResponse(BaseModel):
    """Password strength check response schema."""
    
    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Şifre gücü skoru (0-100)"
    )
    ok: bool = Field(
        ...,
        description="Şifre minimum gereksinimleri karşılıyor mu?"
    )
    feedback: List[str] = Field(
        ...,
        description="Şifre iyileştirme önerileri",
        example=["Şifre en az 12 karakter olmalıdır", "Özel karakter ekleyin"]
    )


class PasswordForgotRequest(BaseModel):
    """Password forgot/reset initiation request schema."""
    
    email: EmailStr = Field(
        ...,
        description="Şifre sıfırlanacak e-posta adresi",
        example="kullanici@example.com"
    )
    
    @validator('email')
    def validate_email(cls, v):
        """Validate and normalize email."""
        return v.lower().strip()


class PasswordForgotResponse(BaseModel):
    """Password forgot response schema."""
    
    message: str = Field(
        default="Şifre sıfırlama bağlantısı e-posta adresinize gönderildi.",
        description="Başarı mesajı"
    )


class PasswordResetRequest(BaseModel):
    """Password reset completion request schema."""
    
    token: str = Field(
        ...,
        min_length=32,
        max_length=128,
        description="Şifre sıfırlama token'ı",
        example="abcd1234..."
    )
    new_password: str = Field(
        ...,
        min_length=12,
        max_length=128,
        description="Yeni şifre (en az 12 karakter)",
        example="YeniGüçlüŞifre123!"
    )


class PasswordResetResponse(BaseModel):
    """Password reset completion response schema."""
    
    message: str = Field(
        default="Şifre başarıyla güncellendi.",
        description="Başarı mesajı"
    )
    user_id: int = Field(..., description="Kullanıcı ID'si")


class AuthErrorResponse(BaseModel):
    """Authentication error response schema."""
    
    error_code: str = Field(
        ...,
        description="Hata kodu",
        example="ERR-AUTH-INVALID-CREDS"
    )
    message: str = Field(
        ...,
        description="Hata mesajı",
        example="E-posta adresi veya şifre hatalı"
    )
    details: Optional[Dict[str, Any]] = Field(
        None,
        description="Ek hata detayları"
    )


class UserProfileResponse(BaseModel):
    """User profile response schema."""
    
    user_id: int = Field(..., description="Kullanıcı ID'si")
    email: str = Field(..., description="E-posta adresi")
    full_name: Optional[str] = Field(None, description="Tam ad")
    display_name: Optional[str] = Field(None, description="Görünen ad")
    role: str = Field(..., description="Kullanıcı rolü")
    account_status: str = Field(..., description="Hesap durumu")
    is_email_verified: bool = Field(..., description="E-posta doğrulandı mı?")
    locale: str = Field(..., description="Dil ayarı")
    timezone: str = Field(..., description="Zaman dilimi")
    created_at: datetime = Field(..., description="Hesap oluşturma tarihi")
    last_login_at: Optional[datetime] = Field(None, description="Son giriş tarihi")
    total_login_count: int = Field(..., description="Toplam giriş sayısı")
    data_processing_consent: bool = Field(..., description="KVKK veri işleme rızası")
    marketing_consent: bool = Field(..., description="Pazarlama iletişimi rızası")


class SecurityEventResponse(BaseModel):
    """Security event response schema for audit logs."""
    
    event_id: int = Field(..., description="Güvenlik olayı ID'si")
    event_type: str = Field(..., description="Olay türü")
    timestamp: datetime = Field(..., description="Olay zamanı")
    ip_address: Optional[str] = Field(None, description="IP adresi (maskelenmiş)")
    user_agent: Optional[str] = Field(None, description="Kullanıcı aracısı")
    details: Dict[str, Any] = Field(..., description="Olay detayları")


# Task 3.3: JWT Token Management Schemas

class TokenRefreshResponse(BaseModel):
    """JWT token refresh response schema."""
    
    access_token: str = Field(..., description="Yeni JWT erişim token'ı")
    token_type: str = Field(default="bearer", description="Token türü")
    expires_in: int = Field(..., description="Token geçerlilik süresi (saniye)")


class LogoutResponse(BaseModel):
    """Logout response schema."""
    
    message: str = Field(
        default="Oturum başarıyla kapatıldı",
        description="Başarı mesajı"
    )


class LogoutAllResponse(BaseModel):
    """Logout all sessions response schema."""
    
    message: str = Field(
        default="Tüm oturumlar başarıyla kapatıldı",
        description="Başarı mesajı"
    )
    sessions_revoked: int = Field(..., description="İptal edilen oturum sayısı")


class SessionInfo(BaseModel):
    """Session information schema."""
    
    session_id: str = Field(..., description="Oturum ID'si")
    created_at: datetime = Field(..., description="Oluşturulma zamanı")
    last_used_at: Optional[datetime] = Field(None, description="Son kullanım zamanı")
    expires_at: datetime = Field(..., description="Geçerlilik sonu")
    is_current: bool = Field(..., description="Mevcut oturum mu?")
    device_fingerprint: Optional[str] = Field(None, description="Cihaz parmak izi (kısaltılmış)")
    ip_address: Optional[str] = Field(None, description="IP adresi (maskelenmiş)")
    is_suspicious: bool = Field(..., description="Şüpheli oturum mu?")
    age_days: int = Field(..., description="Oturum yaşı (gün)")
    expires_in_days: int = Field(..., description="Geçerlilik süresi (gün)")


class ActiveSessionsResponse(BaseModel):
    """Active sessions list response schema."""
    
    sessions: List[SessionInfo] = Field(..., description="Aktif oturum listesi")
    total_count: int = Field(..., description="Toplam oturum sayısı")
    current_session_id: str = Field(..., description="Mevcut oturum ID'si")


# Error code mappings for consistent error responses
AUTH_ERROR_CODES = {
    'ERR-AUTH-INVALID-BODY': 'Geçersiz istek verisi',
    'ERR-AUTH-INVALID-CREDS': 'E-posta adresi veya şifre hatalı',
    'ERR-AUTH-LOCKED': 'Hesap geçici olarak kilitlendi',
    'ERR-AUTH-EMAIL-TAKEN': 'Bu e-posta adresi zaten kullanılmaktadır',
    'ERR-AUTH-WEAK-PASSWORD': 'Şifre güvenlik gereksinimlerini karşılamıyor',
    'ERR-AUTH-ACCOUNT-INACTIVE': 'Hesap aktif değil',
    'ERR-AUTH-PASSWORD-EXPIRED': 'Şifre süresi dolmuş',
    'ERR-AUTH-INVALID-TOKEN': 'Geçersiz veya süresi dolmuş token',
    'ERR-AUTH-REGISTRATION-FAILED': 'Kayıt işlemi başarısız',
    'ERR-AUTH-RESET-FAILED': 'Şifre sıfırlama işlemi başarısız',
    'ERR-AUTH-SYSTEM-ERROR': 'Sistem hatası',
    
    # Task 3.3: JWT-specific error codes
    'ERR-TOKEN-INVALID': 'Geçersiz token',
    'ERR-TOKEN-EXPIRED': 'Token süresi dolmuş',
    'ERR-TOKEN-REVOKED': 'Token iptal edilmiş',
    'ERR-TOKEN-MALFORMED': 'Token formatı geçersiz',
    'ERR-REFRESH-MISSING': 'Refresh token bulunamadı',
    'ERR-REFRESH-INVALID': 'Refresh token geçersiz veya süresi dolmuş',
    'ERR-REFRESH-REUSE': 'Refresh token yeniden kullanım girişimi tespit edildi',
    'ERR-REFRESH-ROTATION-FAILED': 'Token rotasyonu başarısız',
    'ERR-LOGOUT-FAILED': 'Oturum kapatma başarısız',
    'ERR-LOGOUT-ALL-FAILED': 'Tüm oturumları kapatma başarısız',
    'ERR-SESSION-NOT-FOUND': 'Oturum bulunamadı',
    'ERR-INSUFFICIENT-SCOPES': 'Yetersiz yetki',
    'ERR-ADMIN-REQUIRED': 'Admin yetkisi gerekli',
    
    # Task 3.6: Magic Link error codes
    'ERR-ML-MALFORMED': 'Magic link formatı geçersiz',
    'ERR-ML-INVALID': 'Magic link geçersiz',
    'ERR-ML-EXPIRED': 'Magic link süresi dolmuş',
    'ERR-ML-ALREADY-USED': 'Magic link zaten kullanılmış',
    'ERR-ML-USER-NOT-FOUND': 'Kullanıcı bulunamadı',
    'ERR-ML-ACCOUNT-LOCKED': 'Hesap kilitli veya aktif değil',
    'ERR-ML-RATE-LIMITED': 'Çok fazla magic link talebi',
    'ERR-ML-CONSUMPTION-FAILED': 'Magic link kullanımı başarısız',
    'ERR-ML-REQUEST-FAILED': 'Magic link talebi başarısız',
    'ERR-ML-SYSTEM-ERROR': 'Magic link sistem hatası',
}