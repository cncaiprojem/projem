"""
OIDC Authentication Router for Task 3.5 - Google OAuth2/OIDC Integration

This router implements ultra enterprise OAuth2/OIDC authentication endpoints:
- GET /auth/oidc/google/start - Initialize OAuth2 flow with PKCE
- GET /auth/oidc/google/callback - Handle OAuth2 callback and authenticate
- GET /auth/oidc/status - Get OIDC configuration status

Banking-level security features:
- PKCE (S256) for authorization code flow
- Cryptographically secure state validation
- Nonce verification for additional security
- Complete audit trail with PII masking
- Turkish error messages and KVKV compliance
"""

from datetime import datetime, timezone
from typing import Dict, Any, Optional
import ipaddress

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Query
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db, get_redis
from ..schemas.oidc_schemas import (
    OIDCAuthStartResponse, OIDCCallbackRequest, OIDCAuthResponse,
    OIDCErrorResponse, OIDCStatusResponse, OIDCUserProfile,
    OIDC_ERROR_CODES, create_oidc_error_response
)
from ..services.oidc_service import oidc_service, OIDCServiceError
from ..services.token_service import token_service
from ..core.logging import get_logger
from ..middleware.auth_limiter import limit
from ..settings import app_settings as settings

logger = get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/auth/oidc",
    tags=["OIDC Kimlik Doğrulama (Google)"],
    responses={
        400: {"model": OIDCErrorResponse, "description": "Geçersiz istek"},
        401: {"model": OIDCErrorResponse, "description": "Kimlik doğrulama hatası"},
        403: {"model": OIDCErrorResponse, "description": "OIDC devre dışı"},
        429: {"model": OIDCErrorResponse, "description": "Çok fazla istek"},
        500: {"model": OIDCErrorResponse, "description": "Sunucu hatası"},
    }
)


def get_client_info(request: Request) -> Dict[str, Optional[str]]:
    """Extract client information from request with enterprise validation."""
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


def create_oidc_error_response_json(error: OIDCServiceError) -> JSONResponse:
    """Create standardized OIDC error response."""
    error_response = create_oidc_error_response(error.code, error.details)
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=error_response.dict()
    )


def check_oidc_enabled():
    """Check if Google OIDC is enabled."""
    if not settings.google_oauth_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=create_oidc_error_response('ERR-OIDC-DISABLED').dict()
        )
    
    if not settings.google_client_id or not settings.google_client_secret:
        logger.error("Google OAuth configuration incomplete", extra={
            'has_client_id': bool(settings.google_client_id),
            'has_client_secret': bool(settings.google_client_secret)
        })
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=create_oidc_error_response('ERR-OIDC-CONFIG-FAILED').dict()
        )


@router.get(
    "/status",
    response_model=OIDCStatusResponse,
    summary="OIDC yapılandırma durumu",
    description="Google OIDC kimlik doğrulama yapılandırma bilgilerini getirir.",
    response_description="OIDC yapılandırma durumu"
)
async def get_oidc_status(request: Request) -> OIDCStatusResponse:
    """
    Get OIDC configuration status.
    
    Returns public configuration information for Google OAuth2/OIDC:
    - Whether OIDC is enabled
    - Client ID (public information)
    - OAuth scopes
    - Redirect URI for current environment
    """
    client_info = get_client_info(request)
    
    # Build redirect URI for current environment
    base_url = str(request.base_url).rstrip('/')
    redirect_uri = f"{base_url}/api/v1/auth/oidc/google/callback"
    
    logger.info("OIDC status requested", extra={
        'operation': 'get_oidc_status',
        'client_ip': client_info["ip_address"],
        'enabled': settings.google_oauth_enabled
    })
    
    return OIDCStatusResponse(
        google_oauth_enabled=settings.google_oauth_enabled,
        client_id=settings.google_client_id if settings.google_oauth_enabled else None,
        scopes=settings.google_oauth_scopes,
        redirect_uri=redirect_uri if settings.google_oauth_enabled else None,
        discovery_url=settings.google_discovery_url
    )


@router.get(
    "/google/start",
    response_model=OIDCAuthStartResponse,
    summary="Google OIDC kimlik doğrulama başlat",
    description="Google OAuth2/OIDC kimlik doğrulama sürecini PKCE ve state ile başlatır.",
    response_description="Google yetkilendirme URL'si ve state parametresi"
)
@limit("10/minute")  # Rate limit: 10 authentication starts per minute
async def start_google_auth(
    request: Request,
    redirect_to: Optional[str] = Query(
        None,
        description="Kimlik doğrulama sonrası yönlendirilecek URL",
        max_length=2048
    ),
    redis_client = Depends(get_redis)
) -> OIDCAuthStartResponse:
    """
    Start Google OAuth2/OIDC authentication flow.
    
    **Security Features:**
    - PKCE (S256) code challenge for enhanced security
    - Cryptographically secure state parameter (CSRF protection)
    - Nonce parameter for ID token validation
    - Server-side secure state storage in Redis
    - Comprehensive audit logging
    
    **Flow:**
    1. Generate PKCE code verifier and challenge
    2. Generate secure state and nonce parameters
    3. Store security parameters server-side
    4. Redirect user to Google authorization endpoint
    
    **Rate Limiting:** 10 requests per minute per IP
    """
    client_info = get_client_info(request)
    
    try:
        # Check if OIDC is enabled
        check_oidc_enabled()
        
        # Build redirect URI
        base_url = str(request.base_url).rstrip('/')
        redirect_uri = f"{base_url}/api/v1/auth/oidc/google/callback"
        
        # Create authorization URL with PKCE and state
        authorization_url, state = await oidc_service.create_authorization_url(
            redis_client=redis_client,
            redirect_uri=redirect_uri,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"]
        )
        
        logger.info("OIDC authentication started", extra={
            'operation': 'start_google_auth',
            'provider': 'google',
            'client_ip': client_info["ip_address"],
            'has_redirect_to': bool(redirect_to),
            'state_length': len(state)
        })
        
        return OIDCAuthStartResponse(
            authorization_url=authorization_url,
            state=state,
            expires_in=settings.oauth_state_expire_minutes * 60,
            message="Google OIDC kimlik doğrulama başlatıldı"
        )
        
    except OIDCServiceError as e:
        logger.warning("OIDC authentication start failed", extra={
            'operation': 'start_google_auth',
            'error_code': e.code,
            'client_ip': client_info["ip_address"]
        })
        return create_oidc_error_response_json(e)
    
    except Exception as e:
        logger.error("Unexpected OIDC start error", exc_info=True, extra={
            'operation': 'start_google_auth',
            'client_ip': client_info["ip_address"],
            'error_type': type(e).__name__
        })
        return create_oidc_error_response_json(OIDCServiceError(
            'ERR-OIDC-AUTH-URL-FAILED',
            'OIDC yetkilendirme URL\'si oluşturulamadı'
        ))


@router.get(
    "/google/callback",
    response_model=OIDCAuthResponse,
    summary="Google OIDC kimlik doğrulama geri çağırma",
    description="Google OAuth2 callback'ini işler ve kullanıcı kimlik doğrulaması yapar.",
    response_description="Başarılı kimlik doğrulama sonucu ve JWT token"
)
@limit("20/minute")  # Rate limit: 20 callback attempts per minute
async def google_auth_callback(
    request: Request,
    response: Response,
    code: str = Query(..., description="Google'dan dönen yetkilendirme kodu"),
    state: str = Query(..., description="OAuth2 state parametresi"),
    error: Optional[str] = Query(None, description="OAuth2 hata kodu"),
    error_description: Optional[str] = Query(None, description="OAuth2 hata açıklaması"),
    db: Session = Depends(get_db),
    redis_client = Depends(get_redis)
) -> OIDCAuthResponse:
    """
    Handle Google OAuth2 callback and authenticate user.
    
    **Security Validation:**
    - State parameter validation (CSRF protection)
    - PKCE code verifier validation
    - Nonce verification in ID token
    - Authorization code exchange with PKCE
    - ID token signature and claims validation
    
    **User Management:**
    - Link to existing user account by email
    - Create new user account if not exists
    - Update OIDC account information
    - Generate JWT access and refresh tokens
    
    **Audit & Compliance:**
    - Complete audit trail logging
    - PII masking in logs (KVKV compliance)
    - Security event logging for failures
    - Turkish error messages
    
    **Rate Limiting:** 20 requests per minute per IP
    """
    client_info = get_client_info(request)
    start_time = datetime.now(timezone.utc)
    
    try:
        # Check if OIDC is enabled
        check_oidc_enabled()
        
        # Check for OAuth2 errors from Google
        if error:
            logger.warning("Google OAuth2 error received", extra={
                'operation': 'google_auth_callback',
                'oauth_error': error,
                'error_description': error_description,
                'client_ip': client_info["ip_address"]
            })
            
            # Map common OAuth2 errors to Turkish messages
            error_messages = {
                'access_denied': 'Kullanıcı erişim izni vermedi',
                'invalid_request': 'Geçersiz OAuth2 isteği',
                'invalid_client': 'Geçersiz OAuth2 istemci',
                'invalid_grant': 'Geçersiz yetkilendirme kodu',
                'unsupported_response_type': 'Desteklenmeyen yanıt türü'
            }
            
            message = error_messages.get(error, f'OAuth2 hatası: {error}')
            return create_oidc_error_response_json(OIDCServiceError(
                'ERR-OIDC-OAUTH-ERROR',
                message,
                {'oauth_error': error, 'description': error_description}
            ))
        
        # Build redirect URI (must match the one used in start)
        base_url = str(request.base_url).rstrip('/')
        redirect_uri = f"{base_url}/api/v1/auth/oidc/google/callback"
        
        # Exchange authorization code for tokens
        token_data = await oidc_service.exchange_code_for_tokens(
            redis_client=redis_client,
            code=code,
            state=state,
            redirect_uri=redirect_uri,
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"]
        )
        
        # Authenticate or create user
        auth_result = await oidc_service.authenticate_or_link_user(
            db=db,
            id_token_claims=token_data['id_token_claims'],
            ip_address=client_info["ip_address"],
            user_agent=client_info["user_agent"]
        )
        
        # Set refresh token cookie
        token_service.set_refresh_cookie(response, auth_result.refresh_token)
        
        # Build OIDC profile
        claims = token_data['id_token_claims']
        oidc_profile = OIDCUserProfile(
            sub=claims['sub'],
            email=claims['email'],
            email_verified=claims.get('email_verified', False),
            name=claims.get('name'),
            picture=claims.get('picture'),
            locale=claims.get('locale')
        )
        
        elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        
        logger.info("OIDC authentication successful", extra={
            'operation': 'google_auth_callback',
            'provider': 'google',
            'user_id': auth_result.user.id,
            'is_new_user': auth_result.is_new_user,
            'is_new_oidc_link': auth_result.is_new_oidc_link,
            'client_ip': client_info["ip_address"],
            'elapsed_ms': elapsed_ms
        })
        
        return OIDCAuthResponse(
            access_token=auth_result.access_token,
            token_type="bearer",
            expires_in=auth_result.expires_in,
            user_id=auth_result.user.id,
            email=auth_result.user.email,
            full_name=auth_result.user.full_name,
            role=auth_result.user.role.value,
            is_new_user=auth_result.is_new_user,
            is_new_oidc_link=auth_result.is_new_oidc_link,
            profile=oidc_profile,
            message="Google OIDC girişi başarılı"
        )
        
    except OIDCServiceError as e:
        logger.warning("OIDC callback failed", extra={
            'operation': 'google_auth_callback',
            'error_code': e.code,
            'client_ip': client_info["ip_address"]
        })
        return create_oidc_error_response_json(e)
    
    except Exception as e:
        logger.error("Unexpected OIDC callback error", exc_info=True, extra={
            'operation': 'google_auth_callback',
            'client_ip': client_info["ip_address"],
            'error_type': type(e).__name__
        })
        return create_oidc_error_response_json(OIDCServiceError(
            'ERR-OIDC-AUTH-FAILED',
            'OIDC kimlik doğrulama başarısız'
        ))


# Additional utility endpoints for OIDC management

@router.post(
    "/logout",
    summary="OIDC oturum kapatma",
    description="OIDC kullanıcısının oturumunu kapatır ve refresh token'ları iptal eder.",
    response_description="Oturum kapatma sonucu"
)
@limit("30/minute")  # Rate limit: 30 logout attempts per minute
async def oidc_logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db)
) -> Dict[str, str]:
    """
    Logout OIDC authenticated user.
    
    **Actions:**
    - Revoke current refresh token
    - Clear refresh token cookie
    - Log logout event for audit
    
    **Security:**
    - Rate limiting to prevent abuse
    - Audit logging for compliance
    - Secure cookie clearing
    """
    client_info = get_client_info(request)
    
    try:
        # Get refresh token from cookie
        refresh_token = token_service.get_refresh_token_from_request(request)
        
        if refresh_token:
            # Revoke the refresh token
            token_service.revoke_refresh_token(
                db=db,
                refresh_token=refresh_token,
                reason='oidc_user_logout'
            )
        
        # Clear refresh token cookie
        token_service.clear_refresh_cookie(response)
        
        logger.info("OIDC logout successful", extra={
            'operation': 'oidc_logout',
            'had_refresh_token': bool(refresh_token),
            'client_ip': client_info["ip_address"]
        })
        
        return {"message": "Oturum başarıyla kapatıldı"}
        
    except Exception as e:
        logger.error("OIDC logout failed", exc_info=True, extra={
            'operation': 'oidc_logout',
            'client_ip': client_info["ip_address"],
            'error_type': type(e).__name__
        })
        # Always return success for logout for security
        return {"message": "Oturum başarıyla kapatıldı"}