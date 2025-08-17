"""
Magic Link Authentication Router for Task 3.6

This router implements banking-level passwordless authentication endpoints:
- POST /auth/magic-link/request - Request magic link (always returns 202)
- POST /auth/magic-link/consume - Consume magic link and create session

Ultra enterprise features:
- Email enumeration protection (always returns success)
- Rate limiting (5 requests per hour per email)
- Cryptographic token validation with 15-minute expiration
- Single-use enforcement with database tracking
- Complete audit trail for security monitoring
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
import ipaddress

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas.magic_link_schemas import (
    MagicLinkRequestRequest, MagicLinkRequestResponse,
    MagicLinkConsumeRequest, MagicLinkConsumeResponse,
    MagicLinkErrorResponse, MAGIC_LINK_ERROR_CODES
)
from ..services.magic_link_service import magic_link_service, MagicLinkError
from ..services.token_service import token_service
from ..core.logging import get_logger
from ..middleware.auth_limiter import limiter
from ..middleware.enterprise_rate_limiter import magic_link_rate_limit

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/auth/magic-link",
    tags=["Magic Link Kimlik Doğrulama"],
    responses={
        400: {"model": MagicLinkErrorResponse, "description": "Geçersiz istek"},
        401: {"model": MagicLinkErrorResponse, "description": "Magic link hatası"},
        429: {"model": MagicLinkErrorResponse, "description": "Çok fazla istek"},
        500: {"model": MagicLinkErrorResponse, "description": "Sunucu hatası"},
    }
)


def get_client_info(request: Request) -> Dict[str, Optional[str]]:
    """Extract client information from request for security audit."""
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


def create_magic_link_error_response(error: MagicLinkError) -> JSONResponse:
    """Create standardized magic link error response."""
    status_code = status.HTTP_400_BAD_REQUEST
    
    # Map specific errors to appropriate status codes
    if error.code in ['ERR-ML-EXPIRED', 'ERR-ML-INVALID', 'ERR-ML-ALREADY-USED']:
        status_code = status.HTTP_401_UNAUTHORIZED
    elif error.code == 'ERR-ML-RATE-LIMITED':
        status_code = status.HTTP_429_TOO_MANY_REQUESTS
    
    return JSONResponse(
        status_code=status_code,
        content={
            "error_code": error.code,
            "message": error.message,
            "details": error.details
        }
    )


@router.post(
    "/request",
    response_model=MagicLinkRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Magic link talebi",
    description="Magic link oluşturur ve e-posta gönderir. Güvenlik için her zaman başarılı yanıt verir.",
    response_description="Magic link talep sonucu"
)
async def request_magic_link(
    request: Request,
    magic_link_data: MagicLinkRequestRequest,
    db: Session = Depends(get_db),
    _rate_limit_check: None = Depends(magic_link_rate_limit)
) -> MagicLinkRequestResponse:
    """
    Magic link talebi oluşturur.
    
    - **email**: Magic link gönderilecek e-posta adresi
    - **device_fingerprint**: İsteğe bağlı cihaz parmak izi (güvenlik için)
    
    **Güvenlik Özellikleri:**
    - E-posta varlığı kontrol edilmez (email enumeration koruması)
    - Rate limiting (e-posta başına saatte 5 talep)
    - 15 dakikalık token geçerliliği
    - Kapsamlı audit loglama
    - Cihaz parmak izi takibi
    
    **Her zaman 202 (Accepted) döner** - güvenlik için e-posta varlığı bilgisi verilmez.
    """
    client_info = get_client_info(request)
    
    try:
        # Request magic link (always returns True for security)
        magic_link_service.request_magic_link(
            db=db,
            email=magic_link_data.email,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"],
            device_fingerprint=magic_link_data.device_fingerprint
        )
        
        logger.info("Magic link request processed", extra={
            'operation': 'request_magic_link_endpoint',
            'email_hash': hash(magic_link_data.email) % 1000000,
            'ip_address': client_info["ip_address"],
            'has_device_fingerprint': bool(magic_link_data.device_fingerprint)
        })
        
        return MagicLinkRequestResponse(
            message="Magic link e-posta adresinize gönderildi. Gelen kutunuzu kontrol edin.",
            expires_in_minutes=15
        )
        
    except MagicLinkError as e:
        logger.warning("Magic link request failed", extra={
            "error_code": e.code,
            "email_hash": hash(magic_link_data.email) % 1000000,
            "ip_address": client_info["ip_address"]
        })
        return create_magic_link_error_response(e)
    
    except Exception as e:
        logger.error("Unexpected magic link request error", exc_info=True, extra={
            "email_hash": hash(magic_link_data.email) % 1000000,
            "ip_address": client_info["ip_address"]
        })
        # Always return success for security (even on system errors)
        return MagicLinkRequestResponse(
            message="Magic link e-posta adresinize gönderildi. Gelen kutunuzu kontrol edin.",
            expires_in_minutes=15
        )


@router.post(
    "/consume",
    response_model=MagicLinkConsumeResponse,
    summary="Magic link kullanımı",
    description="Magic link token'ını kullanarak kimlik doğrulaması yapar ve oturum oluşturur.",
    response_description="Başarılı magic link kullanım sonucu"
)
@limiter.limit("10/minute")  # Rate limit: 10 consumption attempts per minute
async def consume_magic_link(
    request: Request,
    response: Response,
    consume_data: MagicLinkConsumeRequest,
    db: Session = Depends(get_db)
) -> MagicLinkConsumeResponse:
    """
    Magic link token'ını kullanarak kimlik doğrulaması yapar.
    
    - **token**: Magic link token'ı (e-posta ile gönderilen)
    - **device_fingerprint**: İsteğe bağlı cihaz parmak izi (güvenlik doğrulaması)
    
    **Güvenlik Özellikleri:**
    - 15 dakikalık token geçerliliği
    - Tek kullanımlık token (single-use enforcement)
    - Cihaz parmak izi doğrulaması
    - Session oluşturma ve JWT token verme
    - Kapsamlı audit loglama
    - Refresh token cookie (HttpOnly, Secure)
    
    **Başarılı kullanım:**
    - JWT access token döner (30 dakika geçerli)
    - Refresh token HttpOnly cookie'de saklanır (7 gün)
    - Kullanıcı bilgileri ve oturum ID'si döner
    """
    client_info = get_client_info(request)
    
    try:
        # Consume magic link and create session
        result = magic_link_service.consume_magic_link(
            db=db,
            token=consume_data.token,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"],
            device_fingerprint=consume_data.device_fingerprint
        )
        
        # Set refresh token in httpOnly cookie
        token_service.set_refresh_cookie(response, result.refresh_token)
        
        logger.info("Magic link consumed successfully", extra={
            'operation': 'consume_magic_link_endpoint',
            'user_id': result.user.id,
            'session_id': result.session_id,
            'ip_address': client_info["ip_address"]
        })
        
        return MagicLinkConsumeResponse(
            access_token=result.access_token,
            token_type="bearer",
            expires_in=result.expires_in,
            user_id=result.user.id,
            email=result.user.email,
            full_name=result.user.full_name,
            role=result.user.role.value if hasattr(result.user.role, 'value') else str(result.user.role),
            session_id=result.session_id,
            login_method="magic_link",
            password_must_change=result.user.password_must_change
        )
        
    except MagicLinkError as e:
        logger.warning("Magic link consumption failed", extra={
            "error_code": e.code,
            "token_prefix": consume_data.token[:8] if len(consume_data.token) >= 8 else "***",
            "ip_address": client_info["ip_address"]
        })
        return create_magic_link_error_response(e)
    
    except Exception as e:
        logger.error("Unexpected magic link consumption error", exc_info=True, extra={
            "token_prefix": consume_data.token[:8] if len(consume_data.token) >= 8 else "***",
            "ip_address": client_info["ip_address"]
        })
        return create_magic_link_error_response(MagicLinkError(
            'ERR-ML-SYSTEM-ERROR',
            'Magic link sistem hatası, lütfen tekrar deneyin'
        ))


# Health check endpoint for magic link service
@router.get(
    "/health",
    summary="Magic link servis durumu",
    description="Magic link servisinin sağlık durumunu kontrol eder.",
    include_in_schema=False  # Hide from public API docs
)
async def magic_link_health_check(
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """Magic link service health check."""
    try:
        # Check database connectivity
        db.execute("SELECT 1")
        
        return {
            "status": "healthy",
            "service": "magic_link",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "1.0.0"
        }
        
    except Exception as e:
        logger.error("Magic link health check failed", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Magic link servisi kullanılamıyor"
        )