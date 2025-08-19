"""
MFA TOTP Schema definitions for Task 3.7 ultra-enterprise authentication.

These schemas define the API contracts for MFA endpoints with Turkish localization and
KVKV compliance for personal data protection.
"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, validator


class MFASetupStartResponse(BaseModel):
    """MFA setup initiation response schema."""

    secret_masked: str = Field(
        ..., description="Maskelenmiş TOTP secret (güvenlik için)", example="ABCD****XYZE"
    )
    otpauth_url: str = Field(
        ...,
        description="TOTP uygulaması için OTPAuth URL",
        example="otpauth://totp/FreeCAD%20CNC%20Platform:user@example.com?secret=SECRET&issuer=FreeCAD%20CNC%20Platform",
    )
    qr_png_base64: str = Field(
        ...,
        description="QR kod PNG formatında base64 kodlanmış",
        example="iVBORw0KGgoAAAANSUhEUgAA...",
    )


class MFASetupVerifyRequest(BaseModel):
    """MFA setup verification request schema."""

    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="TOTP uygulamasından alınan 6 haneli kod",
        example="123456",
    )

    @validator("code")
    def validate_code(cls, v):
        """Validate TOTP code format."""
        if not v.isdigit():
            raise ValueError("MFA kodu sadece rakam içermelidir")
        return v


class MFASetupVerifyResponse(BaseModel):
    """MFA setup verification response schema."""

    message: str = Field(..., description="Başarı mesajı", example="MFA başarıyla etkinleştirildi")
    backup_codes: List[str] = Field(
        ...,
        description="Tek kullanımlık yedek kodlar (güvenli bir yerde saklayın)",
        example=["ABCD1234", "EFGH5678", "IJKL9012"],
    )


class MFADisableRequest(BaseModel):
    """MFA disable request schema."""

    code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        description="TOTP uygulamasından alınan 6 haneli kod",
        example="123456",
    )

    @validator("code")
    def validate_code(cls, v):
        """Validate TOTP code format."""
        if not v.isdigit():
            raise ValueError("MFA kodu sadece rakam içermelidir")
        return v


class MFADisableResponse(BaseModel):
    """MFA disable response schema."""

    message: str = Field(
        ..., description="Başarı mesajı", example="MFA başarıyla devre dışı bırakıldı"
    )


class MFAChallengeRequest(BaseModel):
    """MFA challenge request schema for login step-up."""

    code: str = Field(
        ...,
        min_length=6,
        max_length=8,
        description="TOTP kodu (6 hane) veya yedek kod (8 hane)",
        example="123456",
    )

    @validator("code")
    def validate_code(cls, v):
        """Validate MFA code format."""
        v = v.upper().strip()
        if len(v) == 6:
            # TOTP code - must be digits
            if not v.isdigit():
                raise ValueError("TOTP kodu sadece rakam içermelidir")
        elif len(v) == 8:
            # Backup code - alphanumeric
            if not v.isalnum():
                raise ValueError("Yedek kod sadece harf ve rakam içermelidir")
        else:
            raise ValueError("Kod 6 haneli TOTP veya 8 haneli yedek kod olmalıdır")
        return v


class MFAChallengeResponse(BaseModel):
    """MFA challenge response schema."""

    access_token: str = Field(..., description="JWT erişim token'ı")
    token_type: str = Field(default="bearer", description="Token türü")
    expires_in: int = Field(..., description="Token geçerlilik süresi (saniye)")
    message: str = Field(default="MFA doğrulaması başarılı", description="Başarı mesajı")


class MFABackupCodesResponse(BaseModel):
    """MFA backup codes generation response schema."""

    backup_codes: List[str] = Field(
        ...,
        description="Yeni yedek kodlar (eskiler geçersiz oldu)",
        example=["ABCD1234", "EFGH5678", "IJKL9012"],
    )
    message: str = Field(
        default="Yeni yedek kodlar oluşturuldu. Güvenli bir yerde saklayın.",
        description="Uyarı mesajı",
    )
    codes_count: int = Field(..., description="Oluşturulan kod sayısı", example=10)


class MFAStatusResponse(BaseModel):
    """MFA status information response schema."""

    mfa_enabled: bool = Field(..., description="MFA etkin mi?")
    mfa_enabled_at: Optional[datetime] = Field(None, description="MFA etkinleştirilme tarihi")
    backup_codes_count: int = Field(..., description="Kalan yedek kod sayısı")
    can_disable_mfa: bool = Field(..., description="MFA devre dışı bırakılabilir mi?")
    requires_mfa: bool = Field(..., description="Bu kullanıcı için MFA zorunlu mu?")


class MFAErrorResponse(BaseModel):
    """MFA error response schema."""

    error_code: str = Field(..., description="Hata kodu", example="ERR-MFA-INVALID")
    message: str = Field(..., description="Hata mesajı", example="MFA kodu geçersiz")
    details: Optional[dict] = Field(None, description="Ek hata detayları")


# Error code mappings for MFA operations
MFA_ERROR_CODES = {
    "ERR-MFA-REQUIRED": "MFA doğrulaması gerekli",
    "ERR-MFA-INVALID": "MFA kodu geçersiz",
    "ERR-MFA-ALREADY-ENABLED": "MFA zaten aktif",
    "ERR-MFA-NOT-ENABLED": "MFA aktif değil",
    "ERR-MFA-SETUP-NOT-STARTED": "MFA kurulumu başlatılmamış",
    "ERR-MFA-RATE-LIMITED": "Çok fazla doğrulama denemesi. Lütfen bekleyin.",
    "ERR-MFA-ADMIN-REQUIRED": "Admin kullanıcılar MFA'yı devre dışı bırakamaz",
    "ERR-MFA-BACKUP-CODE-EXHAUSTED": "Tüm yedek kodlar kullanılmış",
    "ERR-MFA-ENCRYPTION-FAILED": "MFA şifresi şifrelenirken hata oluştu",
    "ERR-MFA-DECRYPTION-FAILED": "MFA şifresi çözülürken hata oluştu",
    "ERR-MFA-SYSTEM-ERROR": "MFA sistem hatası",
}


# Extended auth error codes to include MFA
EXTENDED_AUTH_ERROR_CODES = {
    # Original auth codes from auth.py
    "ERR-AUTH-INVALID-BODY": "Geçersiz istek verisi",
    "ERR-AUTH-INVALID-CREDS": "E-posta adresi veya şifre hatalı",
    "ERR-AUTH-LOCKED": "Hesap geçici olarak kilitlendi",
    "ERR-AUTH-EMAIL-TAKEN": "Bu e-posta adresi zaten kullanılmaktadır",
    "ERR-AUTH-WEAK-PASSWORD": "Şifre güvenlik gereksinimlerini karşılamıyor",
    "ERR-AUTH-ACCOUNT-INACTIVE": "Hesap aktif değil",
    "ERR-AUTH-PASSWORD-EXPIRED": "Şifre süresi dolmuş",
    "ERR-AUTH-INVALID-TOKEN": "Geçersiz veya süresi dolmuş token",
    "ERR-AUTH-REGISTRATION-FAILED": "Kayıt işlemi başarısız",
    "ERR-AUTH-RESET-FAILED": "Şifre sıfırlama işlemi başarısız",
    "ERR-AUTH-SYSTEM-ERROR": "Sistem hatası",
    # JWT specific codes
    "ERR-TOKEN-INVALID": "Geçersiz token",
    "ERR-TOKEN-EXPIRED": "Token süresi dolmuş",
    "ERR-TOKEN-REVOKED": "Token iptal edilmiş",
    "ERR-TOKEN-MALFORMED": "Token formatı geçersiz",
    "ERR-REFRESH-MISSING": "Refresh token bulunamadı",
    "ERR-REFRESH-INVALID": "Refresh token geçersiz veya süresi dolmuş",
    "ERR-REFRESH-REUSE": "Refresh token yeniden kullanım girişimi tespit edildi",
    "ERR-REFRESH-ROTATION-FAILED": "Token rotasyonu başarısız",
    "ERR-LOGOUT-FAILED": "Oturum kapatma başarısız",
    "ERR-LOGOUT-ALL-FAILED": "Tüm oturumları kapatma başarısız",
    "ERR-SESSION-NOT-FOUND": "Oturum bulunamadı",
    "ERR-INSUFFICIENT-SCOPES": "Yetersiz yetki",
    "ERR-ADMIN-REQUIRED": "Admin yetkisi gerekli",
    # Magic Link codes
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
    # MFA codes
    **MFA_ERROR_CODES,
}
