"""
Ultra Enterprise JWT Authentication Router for Task 3.3

This router implements banking-level JWT authentication endpoints:
- POST /auth/token/refresh - Refresh access token with rotation
- POST /auth/logout - Logout current session
- POST /auth/logout/all - Logout all sessions for user

Security features:
- Refresh token rotation with reuse detection
- HttpOnly cookie security with enterprise attributes
- Complete session chain revocation on security events
- Turkish localized error messages
- Comprehensive audit logging
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DBSession

from ..db import get_db
from ..schemas.auth import (
    TokenRefreshResponse,
    LogoutResponse,
    LogoutAllResponse,
    AuthErrorResponse,
    ActiveSessionsResponse,
)
from ..services.token_service import token_service, TokenServiceError
from ..services.jwt_service import jwt_service
from ..middleware.jwt_middleware import get_current_user, AuthenticatedUser
from ..core.logging import get_logger
from ..models.audit_log import AuditLog
from ..middleware.enterprise_rate_limiter import token_refresh_rate_limit

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/auth",
    tags=["JWT Token Management"],
    responses={
        400: {"model": AuthErrorResponse, "description": "Geçersiz istek"},
        401: {"model": AuthErrorResponse, "description": "Kimlik doğrulama hatası"},
        500: {"model": AuthErrorResponse, "description": "Sunucu hatası"},
    },
)


@router.post(
    "/token/refresh",
    response_model=TokenRefreshResponse,
    summary="Access token yenileme",
    description="""
    Refresh token kullanarak yeni access token alın.
    
    Bu endpoint:
    - Refresh token'ı httpOnly cookie'den okur
    - Token rotasyonu yapar (eski token iptal edilir)
    - Yeni access token ve refresh token döner
    - Refresh token yeniden kullanım saldırılarını tespit eder
    
    Güvenlik özellikleri:
    - Otomatik refresh token rotasyonu
    - Reuse detection ile session chain revocation
    - Device fingerprint anomaly detection
    - Complete audit trail
    """,
    responses={
        200: {"description": "Token başarıyla yenilendi", "model": TokenRefreshResponse},
        401: {
            "description": "Geçersiz refresh token",
            "content": {
                "application/json": {
                    "examples": {
                        "invalid_token": {
                            "summary": "Geçersiz refresh token",
                            "value": {
                                "error_code": "ERR-REFRESH-INVALID",
                                "message": "Refresh token geçersiz veya süresi dolmuş",
                                "details": {},
                            },
                        },
                        "reuse_detected": {
                            "summary": "Token reuse saldırısı",
                            "value": {
                                "error_code": "ERR-REFRESH-REUSE",
                                "message": "Refresh token yeniden kullanım girişimi tespit edildi. Güvenlik nedeniyle tüm oturumlar sonlandırıldı.",
                                "details": {},
                            },
                        },
                    }
                }
            },
        },
    },
)
async def refresh_access_token(
    request: Request,
    response: Response,
    db: DBSession = Depends(get_db),
    _rate_limit_check: None = Depends(token_refresh_rate_limit),
):
    """
    Refresh access token using refresh token from httpOnly cookie.
    Implements automatic token rotation and reuse detection.
    """
    start_time = datetime.now(timezone.utc)

    try:
        # Extract refresh token from httpOnly cookie
        refresh_token = token_service.get_refresh_token_from_request(request)
        if not refresh_token:
            logger.warning(
                "Refresh token missing in request",
                extra={
                    "operation": "refresh_access_token",
                    "has_cookies": bool(request.cookies),
                    "cookie_names": list(request.cookies.keys()),
                },
            )

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "error_code": "ERR-REFRESH-MISSING",
                    "message": "Refresh token bulunamadı. Lütfen tekrar giriş yapın.",
                    "details": {},
                },
            )

        # Extract client information for security analysis
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")
        device_fingerprint = request.headers.get("X-Device-Fingerprint")

        # Rotate refresh token (includes reuse detection)
        result = token_service.rotate_refresh_token(
            db=db,
            current_refresh_token=refresh_token,
            device_fingerprint=device_fingerprint,
            ip_address=client_ip,
            user_agent=user_agent,
        )

        # Set new refresh token in httpOnly cookie
        token_service.set_refresh_cookie(response, result.refresh_token)

        elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        logger.info(
            "Access token refreshed successfully",
            extra={
                "operation": "refresh_access_token",
                "user_id": result.session.user_id,
                "old_session_id": str(result.session.rotated_from)
                if result.session.rotated_from
                else None,
                "new_session_id": str(result.session.id),
                "elapsed_ms": elapsed_ms,
            },
        )

        return TokenRefreshResponse(
            access_token=result.access_token, token_type="bearer", expires_in=result.expires_in
        )

    except TokenServiceError as e:
        # Convert token service errors to HTTP responses
        status_mapping = {
            "ERR-REFRESH-INVALID": status.HTTP_401_UNAUTHORIZED,
            "ERR-REFRESH-REUSE": status.HTTP_401_UNAUTHORIZED,
            "ERR-REFRESH-ROTATION-FAILED": status.HTTP_500_INTERNAL_SERVER_ERROR,
        }

        raise HTTPException(
            status_code=status_mapping.get(e.code, status.HTTP_401_UNAUTHORIZED),
            detail={"error_code": e.code, "message": e.message, "details": e.details},
        )

    except Exception as e:
        logger.error(
            "Token refresh failed",
            exc_info=True,
            extra={"operation": "refresh_access_token", "error_type": type(e).__name__},
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "ERR-REFRESH-FAILED",
                "message": "Token yenileme başarısız. Lütfen tekrar deneyin.",
                "details": {"error_type": type(e).__name__},
            },
        )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    summary="Oturum kapatma",
    description="""
    Mevcut oturumu kapatır ve refresh token'ı iptal eder.
    
    Bu endpoint:
    - Mevcut session'ı iptal eder
    - Refresh token cookie'sini temizler
    - JWT access token'larını geçersiz kılar
    - Audit log kaydı oluşturur
    
    Güvenlik özellikleri:
    - Immediate session revocation
    - Secure cookie clearing
    - Complete audit trail
    """,
    responses={
        204: {"description": "Logout başarılı", "model": LogoutResponse},
        401: {"description": "Geçersiz authentication", "model": AuthErrorResponse},
    },
)
async def logout_current_session(
    request: Request,
    response: Response,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    Logout current session and revoke refresh token.
    """
    start_time = datetime.now(timezone.utc)

    try:
        # Get refresh token from cookie for revocation
        refresh_token = token_service.get_refresh_token_from_request(request)

        # Revoke current session
        if refresh_token:
            token_service.revoke_refresh_token(
                db=db, refresh_token=refresh_token, reason="user_logout"
            )
        else:
            # Fallback: revoke by session ID if no refresh token
            token_service.session_service.revoke_session(
                db=db, session_id=current_user.session_id, reason="user_logout"
            )

        # Clear refresh token cookie
        token_service.clear_refresh_cookie(response)

        # Log audit event
        audit_log = AuditLog(
            user_id=current_user.user_id,
            action="user_logout",
            description=f"Kullanıcı oturumu kapattı: {current_user.session_id}",
            details={
                "session_id": str(current_user.session_id),
                "logout_method": "manual",
                "had_refresh_token": bool(refresh_token),
            },
        )
        db.add(audit_log)
        db.commit()

        elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        logger.info(
            "User logged out successfully",
            extra={
                "operation": "logout_current_session",
                "user_id": current_user.user_id,
                "session_id": str(current_user.session_id),
                "elapsed_ms": elapsed_ms,
            },
        )

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except Exception as e:
        db.rollback()
        logger.error(
            "Logout failed",
            exc_info=True,
            extra={
                "operation": "logout_current_session",
                "user_id": current_user.user_id,
                "session_id": str(current_user.session_id),
                "error_type": type(e).__name__,
            },
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "ERR-LOGOUT-FAILED",
                "message": "Oturum kapatma başarısız. Lütfen tekrar deneyin.",
                "details": {"error_type": type(e).__name__},
            },
        )


@router.post(
    "/logout/all",
    response_model=LogoutAllResponse,
    summary="Tüm oturumları kapatma",
    description="""
    Kullanıcının tüm aktif oturumlarını kapatır.
    
    Bu endpoint:
    - Kullanıcının tüm session'larını iptal eder
    - Tüm refresh token'ları geçersiz kılar
    - Tüm JWT access token'larını geçersiz kılar
    - Refresh token cookie'sini temizler
    - Complete audit trail oluşturur
    
    Güvenlik özellikleri:
    - Global session revocation
    - All device logout
    - Security event logging
    - Complete forensic audit
    """,
    responses={
        204: {"description": "Tüm oturumlar kapatıldı", "model": LogoutAllResponse},
        401: {"description": "Geçersiz authentication", "model": AuthErrorResponse},
    },
)
async def logout_all_sessions(
    response: Response,
    current_user: AuthenticatedUser = Depends(get_current_user),
    db: DBSession = Depends(get_db),
):
    """
    Logout all sessions for the current user.
    """
    start_time = datetime.now(timezone.utc)

    try:
        # Revoke all refresh tokens for user
        revoked_count = token_service.revoke_all_refresh_tokens(
            db=db, user_id=current_user.user_id, reason="user_logout_all"
        )

        # Clear refresh token cookie (current session)
        token_service.clear_refresh_cookie(response)

        # Log audit event
        audit_log = AuditLog(
            user_id=current_user.user_id,
            action="user_logout_all",
            description=f"Kullanıcı tüm oturumları kapattı: {revoked_count} oturum iptal edildi",
            details={
                "sessions_revoked": revoked_count,
                "logout_method": "logout_all",
                "initiating_session_id": str(current_user.session_id),
            },
        )
        db.add(audit_log)
        db.commit()

        elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

        logger.info(
            "All user sessions logged out",
            extra={
                "operation": "logout_all_sessions",
                "user_id": current_user.user_id,
                "sessions_revoked": revoked_count,
                "elapsed_ms": elapsed_ms,
            },
        )

        return Response(status_code=status.HTTP_204_NO_CONTENT)

    except Exception as e:
        db.rollback()
        logger.error(
            "Logout all failed",
            exc_info=True,
            extra={
                "operation": "logout_all_sessions",
                "user_id": current_user.user_id,
                "error_type": type(e).__name__,
            },
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "ERR-LOGOUT-ALL-FAILED",
                "message": "Tüm oturumları kapatma başarısız. Lütfen tekrar deneyin.",
                "details": {"error_type": type(e).__name__},
            },
        )


@router.get(
    "/sessions",
    summary="Aktif oturumları listeleme",
    description="""
    Kullanıcının aktif oturumlarını listeler.
    
    Güvenlik bilgileri:
    - Session ID'leri
    - Oluşturulma tarihleri
    - Son kullanım tarihleri
    - Device fingerprint bilgileri
    - IP adres bilgileri (maskelenmiş)
    """,
    response_model=ActiveSessionsResponse,
)
async def list_active_sessions(
    current_user: AuthenticatedUser = Depends(get_current_user), db: DBSession = Depends(get_db)
):
    """
    List active sessions for the current user.
    """
    try:
        # Get active sessions for user
        active_sessions = (
            db.query(Session)
            .filter(Session.user_id == current_user.user_id, Session.revoked_at.is_(None))
            .order_by(Session.created_at.desc())
            .all()
        )

        sessions_data = []
        for session in active_sessions:
            session_data = {
                "session_id": str(session.id),
                "created_at": session.created_at.isoformat(),
                "last_used_at": session.last_used_at.isoformat() if session.last_used_at else None,
                "expires_at": session.expires_at.isoformat(),
                "is_current": session.id == current_user.session_id,
                "device_fingerprint": session.device_fingerprint[:20] + "..."
                if session.device_fingerprint
                else None,
                "ip_address": session.ip_address,  # Already masked in storage
                "is_suspicious": session.is_suspicious,
                "age_days": session.age_in_seconds // (24 * 3600),
                "expires_in_days": max(0, session.expires_in_seconds // (24 * 3600)),
            }
            sessions_data.append(session_data)

        logger.info(
            "Active sessions listed",
            extra={
                "operation": "list_active_sessions",
                "user_id": current_user.user_id,
                "session_count": len(sessions_data),
            },
        )

        return {
            "sessions": sessions_data,
            "total_count": len(sessions_data),
            "current_session_id": str(current_user.session_id),
        }

    except Exception as e:
        logger.error(
            "List sessions failed",
            exc_info=True,
            extra={
                "operation": "list_active_sessions",
                "user_id": current_user.user_id,
                "error_type": type(e).__name__,
            },
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error_code": "ERR-LIST-SESSIONS-FAILED",
                "message": "Oturum listesi alınamadı",
                "details": {"error_type": type(e).__name__},
            },
        )
