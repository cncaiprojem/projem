"""
Ultra Enterprise Authentication Router for Task 3.1

This router implements banking-level authentication endpoints:
- POST /auth/register - User registration with KVKV compliance
- POST /auth/login - Secure login with account lockout protection
- POST /auth/password/strength - Password strength validation
- POST /auth/password/forgot - Password reset initiation
- POST /auth/password/reset - Password reset completion
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
import ipaddress

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas.auth import (
    UserRegisterRequest, UserRegisterResponse,
    UserLoginRequest, UserLoginResponse,
    PasswordStrengthRequest, PasswordStrengthResponse,
    PasswordForgotRequest, PasswordForgotResponse,
    PasswordResetRequest, PasswordResetResponse,
    AuthErrorResponse, UserProfileResponse,
    AUTH_ERROR_CODES
)
from ..services.auth_service import auth_service, AuthenticationError
from ..services.password_service import password_service
# Legacy auth import disabled - using new JWT system
# from ..auth import create_token_pair, get_current_user
from ..services.token_service import token_service
from ..services.jwt_service import jwt_service
from ..schemas import UserOut
from ..core.logging import get_logger
from ..middleware.auth_limiter import limiter
from ..settings import app_settings as settings

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["Kimlik Doğrulama (Enterprise)"],
    responses={
        400: {"model": AuthErrorResponse, "description": "Geçersiz istek"},
        401: {"model": AuthErrorResponse, "description": "Kimlik doğrulama hatası"},
        429: {"model": AuthErrorResponse, "description": "Çok fazla istek"},
        500: {"model": AuthErrorResponse, "description": "Sunucu hatası"},
    }
)


def get_client_info(request: Request) -> Dict[str, Optional[str]]:
    """Extract client information from request."""
    # Get real IP address (handle proxy headers)
    ip_address = None
    if "x-forwarded-for" in request.headers:
        # Take first IP if multiple (proxy chain)
        ip_address = request.headers["x-forwarded-for"].split(",")[0].strip()
    elif "x-real-ip" in request.headers:
        ip_address = request.headers["x-real-ip"]
    else:
        ip_address = getattr(request.client, 'host', None)
    
    # Validate IP address
    if ip_address:
        try:
            ipaddress.ip_address(ip_address)
        except ValueError:
            ip_address = None
    
    user_agent = request.headers.get("user-agent")
    
    return {
        "ip_address": ip_address,
        "user_agent": user_agent
    }


def create_auth_error_response(error: AuthenticationError) -> JSONResponse:
    """Create standardized authentication error response."""
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "error_code": error.code,
            "message": error.message,
            "details": error.details
        }
    )


@router.post(
    "/register",
    response_model=UserRegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Kullanıcı kaydı",
    description="Yeni kullanıcı kaydı oluşturur. KVKV uyumlu veri işleme rızası gereklidir.",
    response_description="Başarılı kayıt sonucu"
)
@limiter.limit("5/minute")  # Rate limit: 5 registration attempts per minute
async def register_user(
    request: Request,
    user_data: UserRegisterRequest,
    db: Session = Depends(get_db)
) -> UserRegisterResponse:
    """
    Kullanıcı kaydı oluşturur.
    
    - **email**: Benzersiz e-posta adresi
    - **password**: En az 12 karakter, büyük/küçük harf, sayı ve özel karakter içermeli
    - **full_name**: İsteğe bağlı tam ad
    - **data_processing_consent**: KVKK veri işleme rızası (zorunlu)
    - **marketing_consent**: Pazarlama iletişimi rızası (isteğe bağlı)
    """
    client_info = get_client_info(request)
    
    try:
        user = auth_service.register_user(
            db=db,
            email=user_data.email,
            password=user_data.password,
            full_name=user_data.full_name,
            data_processing_consent=user_data.data_processing_consent,
            marketing_consent=user_data.marketing_consent,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"]
        )
        
        return UserRegisterResponse(
            user_id=user.id,
            email=user.email,
            message="Kayıt başarılı. E-posta doğrulama bağlantısı gönderildi."
        )
        
    except AuthenticationError as e:
        logger.warning("User registration failed", extra={
            "error_code": e.code,
            "email": user_data.email,
            "ip_address": client_info["ip_address"]
        })
        return create_auth_error_response(e)
    
    except Exception as e:
        logger.error("Unexpected registration error", exc_info=True, extra={
            "email": user_data.email,
            "ip_address": client_info["ip_address"]
        })
        return create_auth_error_response(AuthenticationError(
            'ERR-AUTH-SYSTEM-ERROR',
            'Sistem hatası, lütfen tekrar deneyin'
        ))


@router.post(
    "/login",
    response_model=UserLoginResponse,
    summary="Kullanıcı girişi",
    description="Kullanıcı kimlik doğrulaması yapar. Başarısız denemeler hesap kilitleme ile sonuçlanabilir.",
    response_description="Başarılı giriş sonucu"
)
@limiter.limit("10/minute")  # Rate limit: 10 login attempts per minute
async def login_user(
    request: Request,
    response: Response,
    login_data: UserLoginRequest,
    db: Session = Depends(get_db)
) -> UserLoginResponse:
    """
    Kullanıcı girişi yapar.
    
    - **email**: Kullanıcı e-posta adresi
    - **password**: Kullanıcı şifresi
    - **device_fingerprint**: İsteğe bağlı cihaz parmak izi
    - **mfa_code**: İki faktörlü doğrulama kodu (gerekirse)
    
    **Güvenlik Özellikleri:**
    - 10 başarısız denemeden sonra 15 dakika hesap kilitleme
    - Timing attack koruması
    - Cihaz parmak izi takibi
    - Kapsamlı audit loglama
    """
    client_info = get_client_info(request)
    
    try:
        user, auth_metadata = auth_service.authenticate_user(
            db=db,
            email=login_data.email,
            password=login_data.password,
            device_fingerprint=login_data.device_fingerprint,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"]
        )
        
        # Create refresh session with JWT access token (Task 3.3)
        token_result = token_service.create_refresh_session(
            db=db,
            user=user,
            device_fingerprint=login_data.device_fingerprint,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"]
        )
        
        # Set refresh token in httpOnly cookie
        token_service.set_refresh_cookie(response, token_result.refresh_token)
        
        return UserLoginResponse(
            access_token=token_result.access_token,
            token_type="bearer",
            expires_in=token_result.expires_in,
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role.value,
            mfa_required=False,  # TODO: Implement MFA
            password_must_change=user.password_must_change
        )
        
    except AuthenticationError as e:
        logger.warning("User login failed", extra={
            "error_code": e.code,
            "email": login_data.email,
            "ip_address": client_info["ip_address"]
        })
        return create_auth_error_response(e)
    
    except Exception as e:
        logger.error("Unexpected login error", exc_info=True, extra={
            "email": login_data.email,
            "ip_address": client_info["ip_address"]
        })
        return create_auth_error_response(AuthenticationError(
            'ERR-AUTH-SYSTEM-ERROR',
            'Sistem hatası, lütfen tekrar deneyin'
        ))


@router.post(
    "/password/strength",
    response_model=PasswordStrengthResponse,
    summary="Şifre gücü kontrolü",
    description="Şifre gücünü ve politika uyumluluğunu kontrol eder.",
    response_description="Şifre gücü analiz sonucu"
)
@limiter.limit("20/minute")  # Rate limit: 20 checks per minute
async def check_password_strength(
    request: Request,
    password_data: PasswordStrengthRequest
) -> PasswordStrengthResponse:
    """
    Şifre gücünü kontrol eder.
    
    - **password**: Kontrol edilecek şifre
    
    **Değerlendirme Kriterleri:**
    - Minimum 12 karakter uzunluk
    - Büyük harf, küçük harf, sayı ve özel karakter
    - Yaygın şifre listesi kontrolü
    - Tekrarlayan desen kontrolü
    - Entropi hesaplaması
    
    **Skor:** 0-100 arası (70+ güçlü kabul edilir)
    """
    try:
        strength_result = password_service.validate_password_strength(password_data.password)
        
        return PasswordStrengthResponse(
            score=strength_result.score,
            ok=strength_result.ok,
            feedback=strength_result.feedback
        )
        
    except Exception as e:
        logger.error("Password strength check failed", exc_info=True, extra={
            "ip_address": get_client_info(request)["ip_address"]
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Şifre kontrolü başarısız"
        )


@router.post(
    "/password/forgot",
    response_model=PasswordForgotResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Şifre sıfırlama talebi",
    description="Şifre sıfırlama sürecini başlatır. Güvenlik için her zaman başarılı yanıt verir.",
    response_description="Şifre sıfırlama talebi sonucu"
)
@limiter.limit("3/minute")  # Rate limit: 3 reset requests per minute
async def forgot_password(
    request: Request,
    forgot_data: PasswordForgotRequest,
    db: Session = Depends(get_db)
) -> PasswordForgotResponse:
    """
    Şifre sıfırlama sürecini başlatır.
    
    - **email**: Şifre sıfırlanacak e-posta adresi
    
    **Güvenlik Özellikleri:**
    - E-posta varlığı kontrol edilmez (güvenlik için)
    - Rate limiting (kullanıcı başına saatte 3 talep)
    - Güvenli token oluşturma (1 saat geçerlilik)
    - Audit loglama
    """
    client_info = get_client_info(request)
    
    try:
        auth_service.initiate_password_reset(
            db=db,
            email=forgot_data.email,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"]
        )
        
        return PasswordForgotResponse(
            message="Şifre sıfırlama bağlantısı e-posta adresinize gönderildi."
        )
        
    except Exception as e:
        logger.error("Password reset initiation failed", exc_info=True, extra={
            "email": forgot_data.email,
            "ip_address": client_info["ip_address"]
        })
        # Always return success for security
        return PasswordForgotResponse(
            message="Şifre sıfırlama bağlantısı e-posta adresinize gönderildi."
        )


@router.post(
    "/password/reset",
    response_model=PasswordResetResponse,
    summary="Şifre sıfırlama tamamlama",
    description="Şifre sıfırlama token'ı ile yeni şifre belirleme.",
    response_description="Şifre sıfırlama sonucu"
)
@limiter.limit("5/minute")  # Rate limit: 5 reset completions per minute
async def reset_password(
    request: Request,
    reset_data: PasswordResetRequest,
    db: Session = Depends(get_db)
) -> PasswordResetResponse:
    """
    Şifre sıfırlama işlemini tamamlar.
    
    - **token**: Şifre sıfırlama token'ı (e-posta ile gönderilen)
    - **new_password**: Yeni şifre (güçlü şifre politikası uygulanır)
    
    **Güvenlik Özellikleri:**
    - Token geçerlilik kontrolü (1 saat)
    - Yeni şifre gücü validasyonu
    - Hesap kilit durumu sıfırlama
    - Audit loglama
    """
    client_info = get_client_info(request)
    
    try:
        user = auth_service.reset_password(
            db=db,
            token=reset_data.token,
            new_password=reset_data.new_password,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"]
        )
        
        return PasswordResetResponse(
            message="Şifre başarıyla güncellendi.",
            user_id=user.id
        )
        
    except AuthenticationError as e:
        logger.warning("Password reset failed", extra={
            "error_code": e.code,
            "token_prefix": reset_data.token[:8],
            "ip_address": client_info["ip_address"]
        })
        return create_auth_error_response(e)
    
    except Exception as e:
        logger.error("Unexpected password reset error", exc_info=True, extra={
            "token_prefix": reset_data.token[:8],
            "ip_address": client_info["ip_address"]
        })
        return create_auth_error_response(AuthenticationError(
            'ERR-AUTH-SYSTEM-ERROR',
            'Sistem hatası, lütfen tekrar deneyin'
        ))


@router.get(
    "/me",
    response_model=UserProfileResponse,
    summary="Kullanıcı profili",
    description="Mevcut kullanıcının profil bilgilerini getirir.",
    response_description="Kullanıcı profil bilgileri"
)
async def get_current_user_profile(
    current_user: UserOut = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> UserProfileResponse:
    """
    Mevcut kullanıcının profil bilgilerini getirir.
    
    **Kimlik doğrulama gereklidir (Bearer token)**
    
    Dönen bilgiler:
    - Temel profil bilgileri
    - Hesap durumu
    - Güvenlik ayarları
    - KVKV rıza durumları
    - Giriş istatistikleri
    """
    try:
        # Get full user details from database
        from ..models.user import User
        user = db.query(User).filter(User.email == current_user.email).first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Kullanıcı bulunamadı"
            )
        
        return UserProfileResponse(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            display_name=user.display_name,
            role=user.role.value,
            account_status=user.account_status,
            is_email_verified=user.is_email_verified,
            locale=user.locale.value,
            timezone=user.timezone,
            created_at=user.created_at,
            last_login_at=user.last_successful_login_at,
            total_login_count=user.total_login_count,
            data_processing_consent=user.data_processing_consent,
            marketing_consent=user.marketing_consent
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get user profile", exc_info=True, extra={
            "user_email": current_user.email
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Profil bilgileri alınamadı"
        )