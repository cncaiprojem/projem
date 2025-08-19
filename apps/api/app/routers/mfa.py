"""
Ultra-Enterprise MFA TOTP Router for Task 3.7

This router implements banking-level MFA endpoints:
- POST /auth/mfa/setup/start - Initiate MFA setup with QR code
- POST /auth/mfa/setup/verify - Verify TOTP and enable MFA
- POST /auth/mfa/disable - Disable MFA (not for admin users)
- POST /auth/mfa/challenge - MFA challenge during login
- GET /auth/mfa/backup-codes - Generate/regenerate backup codes
- GET /auth/mfa/status - Get MFA status information
"""

from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas.mfa import (
    MFASetupStartResponse,
    MFASetupVerifyRequest,
    MFASetupVerifyResponse,
    MFADisableRequest,
    MFADisableResponse,
    MFAChallengeRequest,
    MFAChallengeResponse,
    MFABackupCodesResponse,
    MFAStatusResponse,
    MFAErrorResponse,
    EXTENDED_AUTH_ERROR_CODES,
)
from ..services.mfa_service import mfa_service, MFAError
from ..services.token_service import token_service
from ..models.user import User
from ..middleware.jwt_middleware import get_current_user, AuthenticatedUser
from ..core.logging import get_logger
from ..middleware.enterprise_rate_limiter import mfa_rate_limit
from ..settings import app_settings as settings

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/auth/mfa",
    tags=["MFA İki Faktörlü Doğrulama (Ultra Enterprise)"],
    responses={
        400: {"model": MFAErrorResponse, "description": "Geçersiz istek"},
        401: {"model": MFAErrorResponse, "description": "Kimlik doğrulama hatası"},
        409: {"model": MFAErrorResponse, "description": "Çakışma hatası"},
        429: {"model": MFAErrorResponse, "description": "Çok fazla istek"},
        500: {"model": MFAErrorResponse, "description": "Sunucu hatası"},
    },
)


def get_client_info(request: Request) -> Dict[str, Optional[str]]:
    """Extract client information from request for audit logging."""
    # Get real IP address (handle proxy headers)
    ip_address = None
    if "x-forwarded-for" in request.headers:
        ip_address = request.headers["x-forwarded-for"].split(",")[0].strip()
    elif "x-real-ip" in request.headers:
        ip_address = request.headers["x-real-ip"]
    else:
        ip_address = getattr(request.client, "host", None)

    user_agent = request.headers.get("user-agent")

    return {"ip_address": ip_address, "user_agent": user_agent}


def create_mfa_error_response(
    error: MFAError, status_code: int = status.HTTP_400_BAD_REQUEST
) -> JSONResponse:
    """Create standardized MFA error response."""
    return JSONResponse(
        status_code=status_code,
        content={"error_code": error.code, "message": error.message, "details": error.details},
    )


@router.post(
    "/setup/start",
    response_model=MFASetupStartResponse,
    summary="MFA kurulum başlatma",
    description="TOTP MFA kurulumunu başlatır ve QR kod ile gizli anahtar döner.",
    response_description="MFA kurulum bilgileri",
)
async def start_mfa_setup(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate_limit_check: None = Depends(mfa_rate_limit),
) -> MFASetupStartResponse:
    """
    MFA kurulumunu başlatır.

    **Kimlik doğrulama gereklidir (Bearer token)**

    Dönen bilgiler:
    - **secret_masked**: Maskelenmiş TOTP gizli anahtarı
    - **otpauth_url**: TOTP uygulaması için OTPAuth URL
    - **qr_png_base64**: QR kod PNG formatında base64 kodlanmış

    **Güvenlik Özellikleri:**
    - AES-256-GCM ile şifrelenmiş secret saklama
    - Güvenli QR kod oluşturma
    - Rate limiting koruması
    - Kapsamlı audit loglama
    """
    client_info = get_client_info(request)

    try:
        # Get full user from database
        user = db.query(User).filter(User.email == current_user.user.email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Kullanıcı bulunamadı"
            )

        setup_data = mfa_service.setup_mfa(
            db=db,
            user=user,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"],
        )

        return MFASetupStartResponse(**setup_data)

    except MFAError as e:
        logger.warning(
            "MFA setup failed",
            extra={
                "error_code": e.code,
                "user_id": current_user.user.id,
                "email": current_user.user.email,
                "ip_address": client_info["ip_address"],
            },
        )

        if e.code == "ERR-MFA-ALREADY-ENABLED":
            return create_mfa_error_response(e, status.HTTP_409_CONFLICT)
        return create_mfa_error_response(e)

    except Exception as e:
        logger.error(
            "Unexpected MFA setup error",
            exc_info=True,
            extra={
                "user_id": current_user.user.id,
                "email": current_user.user.email,
                "ip_address": client_info["ip_address"],
            },
        )
        return create_mfa_error_response(
            MFAError("ERR-MFA-SYSTEM-ERROR", "MFA kurulumu sırasında sistem hatası"),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post(
    "/setup/verify",
    response_model=MFASetupVerifyResponse,
    summary="MFA kurulum doğrulama",
    description="TOTP kodunu doğrulayarak MFA'yı etkinleştirir ve yedek kodlar oluşturur.",
    response_description="MFA etkinleştirme sonucu ve yedek kodlar",
)
async def verify_mfa_setup(
    request: Request,
    verify_data: MFASetupVerifyRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate_limit_check: None = Depends(mfa_rate_limit),
) -> MFASetupVerifyResponse:
    """
    MFA kurulum doğrulaması yapar ve etkinleştirir.

    **Kimlik doğrulama gereklidir (Bearer token)**

    - **code**: TOTP uygulamasından alınan 6 haneli kod

    **Güvenlik Özellikleri:**
    - TOTP kod doğrulaması (±30 saniye tolerance)
    - 10 adet tek kullanımlık yedek kod oluşturma
    - SHA-256 ile hashlenmiş yedek kod saklama
    - Rate limiting koruması
    - Timing attack koruması
    """
    client_info = get_client_info(request)

    try:
        # Get full user from database
        user = db.query(User).filter(User.email == current_user.user.email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Kullanıcı bulunamadı"
            )

        result = mfa_service.verify_and_enable_mfa(
            db=db,
            user=user,
            code=verify_data.code,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"],
        )

        return MFASetupVerifyResponse(
            message=result["message"], backup_codes=result["backup_codes"]
        )

    except MFAError as e:
        logger.warning(
            "MFA verification failed",
            extra={
                "error_code": e.code,
                "user_id": current_user.user.id,
                "email": current_user.user.email,
                "ip_address": client_info["ip_address"],
            },
        )

        if e.code == "ERR-MFA-ALREADY-ENABLED":
            return create_mfa_error_response(e, status.HTTP_409_CONFLICT)
        elif e.code in ["ERR-MFA-INVALID", "ERR-MFA-RATE-LIMITED"]:
            return create_mfa_error_response(e, status.HTTP_401_UNAUTHORIZED)
        return create_mfa_error_response(e)

    except Exception as e:
        logger.error(
            "Unexpected MFA verification error",
            exc_info=True,
            extra={
                "user_id": current_user.user.id,
                "email": current_user.user.email,
                "ip_address": client_info["ip_address"],
            },
        )
        return create_mfa_error_response(
            MFAError("ERR-MFA-SYSTEM-ERROR", "MFA doğrulama sırasında sistem hatası"),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post(
    "/disable",
    response_model=MFADisableResponse,
    summary="MFA devre dışı bırakma",
    description="TOTP kodu ile MFA'yı devre dışı bırakır (admin kullanıcılar için yasak).",
    response_description="MFA devre dışı bırakma sonucu",
)
async def disable_mfa(
    request: Request,
    disable_data: MFADisableRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate_limit_check: None = Depends(mfa_rate_limit),
) -> MFADisableResponse:
    """
    MFA'yı devre dışı bırakır.

    **Kimlik doğrulama gereklidir (Bearer token)**
    **Admin kullanıcılar MFA'yı devre dışı bırakamaz (güvenlik)**

    - **code**: TOTP uygulamasından alınan 6 haneli kod

    **Güvenlik Özellikleri:**
    - TOTP kod doğrulaması zorunlu
    - Tüm yedek kodları siler
    - Admin kullanıcılar için engelleme
    - Kapsamlı audit loglama
    """
    client_info = get_client_info(request)

    try:
        # Get full user from database
        user = db.query(User).filter(User.email == current_user.user.email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Kullanıcı bulunamadı"
            )

        result = mfa_service.disable_mfa(
            db=db,
            user=user,
            code=disable_data.code,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"],
        )

        return MFADisableResponse(message=result["message"])

    except MFAError as e:
        logger.warning(
            "MFA disable failed",
            extra={
                "error_code": e.code,
                "user_id": current_user.user.id,
                "email": current_user.user.email,
                "ip_address": client_info["ip_address"],
            },
        )

        if e.code == "ERR-MFA-NOT-ENABLED":
            return create_mfa_error_response(e, status.HTTP_400_BAD_REQUEST)
        elif e.code in ["ERR-MFA-INVALID", "ERR-MFA-ADMIN-REQUIRED"]:
            return create_mfa_error_response(e, status.HTTP_401_UNAUTHORIZED)
        elif e.code == "ERR-MFA-RATE-LIMITED":
            return create_mfa_error_response(e, status.HTTP_429_TOO_MANY_REQUESTS)
        return create_mfa_error_response(e)

    except Exception as e:
        logger.error(
            "Unexpected MFA disable error",
            exc_info=True,
            extra={
                "user_id": current_user.user.id,
                "email": current_user.user.email,
                "ip_address": client_info["ip_address"],
            },
        )
        return create_mfa_error_response(
            MFAError("ERR-MFA-SYSTEM-ERROR", "MFA devre dışı bırakma sırasında sistem hatası"),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post(
    "/challenge",
    response_model=MFAChallengeResponse,
    summary="MFA doğrulama challenge",
    description="Login sırasında MFA challenge'ı. TOTP veya yedek kod kabul eder.",
    response_description="MFA challenge sonucu ve access token",
)
async def mfa_challenge(
    request: Request,
    response: Response,
    challenge_data: MFAChallengeRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate_limit_check: None = Depends(mfa_rate_limit),
) -> MFAChallengeResponse:
    """
    MFA challenge işlemi (login akışı sonrası).

    **Kimlik doğrulama gereklidir (Bearer token)**
    **Bu endpoint sadece MFA etkin kullanıcılar için çalışır**

    - **code**: TOTP kodu (6 hane) veya yedek kod (8 hane)

    **Güvenlik Özellikleri:**
    - TOTP ve yedek kod desteği
    - Tek kullanımlık yedek kodlar
    - Rate limiting koruması
    - Session temelli doğrulama
    """
    client_info = get_client_info(request)

    try:
        # Get full user from database
        user = db.query(User).filter(User.email == current_user.user.email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Kullanıcı bulunamadı"
            )

        # Check if user has MFA enabled
        if not user.mfa_enabled:
            raise MFAError("ERR-MFA-NOT-ENABLED", "MFA aktif değil")

        # Determine if it's TOTP or backup code
        is_totp = len(challenge_data.code) == 6
        is_backup = len(challenge_data.code) == 8

        verification_success = False

        if is_totp:
            # Verify TOTP code
            verification_success = mfa_service.verify_totp_code(
                db=db,
                user=user,
                code=challenge_data.code,
                ip_address=client_info["ip_address"],
                user_agent=client_info["user_agent"],
            )
        elif is_backup:
            # Verify backup code
            verification_success = mfa_service.verify_backup_code(
                db=db,
                user=user,
                code=challenge_data.code,
                ip_address=client_info["ip_address"],
                user_agent=client_info["user_agent"],
            )
        else:
            raise MFAError("ERR-MFA-INVALID", "MFA kodu geçersiz format")

        if verification_success:
            # MFA challenge successful - create new session
            token_result = token_service.create_refresh_session(
                db=db,
                user=user,
                device_fingerprint=None,  # Get from request if needed
                ip_address=client_info["ip_address"],
                user_agent=client_info["user_agent"],
            )

            # Set refresh token in httpOnly cookie
            token_service.set_refresh_cookie(response, token_result.refresh_token)

            return MFAChallengeResponse(
                access_token=token_result.access_token,
                token_type="bearer",
                expires_in=token_result.expires_in,
                message="MFA doğrulaması başarılı",
            )
        else:
            raise MFAError("ERR-MFA-INVALID", "MFA kodu geçersiz")

    except MFAError as e:
        logger.warning(
            "MFA challenge failed",
            extra={
                "error_code": e.code,
                "user_id": current_user.user.id,
                "email": current_user.user.email,
                "ip_address": client_info["ip_address"],
            },
        )

        if e.code in ["ERR-MFA-INVALID", "ERR-MFA-NOT-ENABLED"]:
            return create_mfa_error_response(e, status.HTTP_401_UNAUTHORIZED)
        elif e.code == "ERR-MFA-RATE-LIMITED":
            return create_mfa_error_response(e, status.HTTP_429_TOO_MANY_REQUESTS)
        return create_mfa_error_response(e)

    except Exception as e:
        logger.error(
            "Unexpected MFA challenge error",
            exc_info=True,
            extra={
                "user_id": current_user.user.id,
                "email": current_user.user.email,
                "ip_address": client_info["ip_address"],
            },
        )
        return create_mfa_error_response(
            MFAError("ERR-MFA-SYSTEM-ERROR", "MFA doğrulama sırasında sistem hatası"),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/backup-codes",
    response_model=MFABackupCodesResponse,
    summary="MFA yedek kodları",
    description="Yeni yedek kodlar oluşturur (eskiler geçersiz olur).",
    response_description="Yeni yedek kodlar",
)
async def get_backup_codes(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: Session = Depends(get_db),
    _rate_limit_check: None = Depends(mfa_rate_limit),
) -> MFABackupCodesResponse:
    """
    MFA yedek kodlarını yeniden oluşturur.

    **Kimlik doğrulama gereklidir (Bearer token)**
    **MFA etkin olmalıdır**

    **ÖNEMLİ:** Bu işlem tüm eski yedek kodları geçersiz kılar!
    Yeni kodları güvenli bir yerde saklamanız gerekmektedir.

    **Güvenlik Özellikleri:**
    - 10 adet yeni tek kullanımlık kod
    - SHA-256 ile hashlenmiş saklama
    - 90 gün geçerlilik süresi
    - Eski kodları otomatik geçersiz kılma
    """
    client_info = get_client_info(request)

    try:
        # Get full user from database
        user = db.query(User).filter(User.email == current_user.user.email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Kullanıcı bulunamadı"
            )

        backup_codes = mfa_service.regenerate_backup_codes(
            db=db,
            user=user,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"],
        )

        return MFABackupCodesResponse(
            backup_codes=backup_codes,
            codes_count=len(backup_codes),
            message="Yeni yedek kodlar oluşturuldu. Güvenli bir yerde saklayın.",
        )

    except MFAError as e:
        logger.warning(
            "Backup codes generation failed",
            extra={
                "error_code": e.code,
                "user_id": current_user.user.id,
                "email": current_user.user.email,
                "ip_address": client_info["ip_address"],
            },
        )

        if e.code == "ERR-MFA-NOT-ENABLED":
            return create_mfa_error_response(e, status.HTTP_400_BAD_REQUEST)
        return create_mfa_error_response(e)

    except Exception as e:
        logger.error(
            "Unexpected backup codes error",
            exc_info=True,
            extra={
                "user_id": current_user.user.id,
                "email": current_user.user.email,
                "ip_address": client_info["ip_address"],
            },
        )
        return create_mfa_error_response(
            MFAError("ERR-MFA-SYSTEM-ERROR", "Yedek kod oluşturma sırasında sistem hatası"),
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.get(
    "/status",
    response_model=MFAStatusResponse,
    summary="MFA durum bilgisi",
    description="Kullanıcının MFA durum bilgilerini getirir.",
    response_description="MFA durum bilgileri",
)
async def get_mfa_status(
    current_user: AuthenticatedUser = Depends(get_current_user), db: Session = Depends(get_db)
) -> MFAStatusResponse:
    """
    Kullanıcının MFA durum bilgilerini getirir.

    **Kimlik doğrulama gereklidir (Bearer token)**

    Dönen bilgiler:
    - MFA etkinleştirilme durumu
    - Etkinleştirilme tarihi
    - Kalan yedek kod sayısı
    - MFA devre dışı bırakılabilirlik durumu
    - MFA zorunluluğu (admin kullanıcılar için)
    """
    try:
        # Get full user from database
        user = db.query(User).filter(User.email == current_user.user.email).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Kullanıcı bulunamadı"
            )

        return MFAStatusResponse(
            mfa_enabled=user.mfa_enabled,
            mfa_enabled_at=user.mfa_enabled_at,
            backup_codes_count=user.mfa_backup_codes_count,
            can_disable_mfa=user.can_disable_mfa(),
            requires_mfa=user.requires_mfa(),
        )

    except Exception as e:
        logger.error(
            "Failed to get MFA status",
            exc_info=True,
            extra={"user_id": current_user.user.id, "email": current_user.user.email},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MFA durum bilgileri alınamadı",
        )
