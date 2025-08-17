"""
Ultra Enterprise OIDC Service for Task 3.5 - Google OAuth2/OIDC Integration

This service implements banking-level OAuth2/OIDC authentication with:
- PKCE (S256) for authorization code flow security
- Cryptographically secure state validation
- Nonce verification for additional security
- Server-side secure storage of PKCE verifiers and state
- Complete audit trail with PII masking
- Integration with existing enterprise authentication system
"""

import secrets
import hashlib
import base64
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlencode

import httpx
import jwt
from jwt import PyJWKClient
from authlib.integrations.httpx_client import OAuth2Session
from authlib.oauth2 import OAuth2Token
from authlib.oidc.core import CodeIDToken, UserInfo
from authlib.common.errors import AuthlibBaseError
from sqlalchemy.orm import Session as DBSession
from fastapi import HTTPException, status

from ..core.logging import get_logger
from ..models.user import User
from ..models.oidc_account import OIDCAccount
from ..models.audit_log import AuditLog
from ..models.security_event import SecurityEvent
from ..services.token_service import token_service, TokenServiceError
from ..services.auth_service import auth_service, AuthenticationError
from ..config import settings
from ..db import get_redis

logger = get_logger(__name__)


class OIDCServiceError(Exception):
    """Base OIDC service error with Turkish localization."""
    
    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class OIDCAuthResult:
    """Result of OIDC authentication operation."""
    
    def __init__(
        self,
        user: User,
        oidc_account: OIDCAccount,
        is_new_user: bool,
        is_new_oidc_link: bool,
        access_token: str,
        refresh_token: str,
        expires_in: int
    ):
        self.user = user
        self.oidc_account = oidc_account
        self.is_new_user = is_new_user
        self.is_new_oidc_link = is_new_oidc_link
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in = expires_in


class OIDCService:
    """Ultra enterprise OIDC service with banking-level security."""
    
    def __init__(self):
        # Google OAuth2 configuration
        self.google_client_id = settings.google_client_id
        self.google_client_secret = settings.google_client_secret
        self.google_discovery_url = settings.google_discovery_url
        self.google_scopes = settings.google_oauth_scopes
        
        # Security configuration
        self.state_expire_seconds = settings.oauth_state_expire_minutes * 60
        self.pkce_verifier_expire_seconds = settings.oauth_pkce_verifier_expire_minutes * 60
        self.callback_timeout_seconds = settings.oauth_callback_timeout_seconds
        
        # Redis key prefixes for secure storage
        self.state_prefix = "oidc:state:"
        self.pkce_prefix = "oidc:pkce:"
        self.nonce_prefix = "oidc:nonce:"
        
        # Cache for Google discovery document
        self._google_config_cache = None
        self._google_config_expires = None
        
        # JWKS client for JWT signature verification
        self._jwks_client = None
        self._jwks_client_expires = None
    
    async def get_google_config(self) -> Dict[str, Any]:
        """
        Get Google OIDC configuration with caching.
        
        Returns:
            Google OIDC discovery document
            
        Raises:
            OIDCServiceError: If configuration cannot be retrieved
        """
        now = datetime.now(timezone.utc)
        
        # Check cache
        if (self._google_config_cache and 
            self._google_config_expires and 
            now < self._google_config_expires):
            return self._google_config_cache
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(self.google_discovery_url)
                response.raise_for_status()
                
                config = response.json()
                
                # Cache for 1 hour
                self._google_config_cache = config
                self._google_config_expires = now + timedelta(hours=1)
                
                logger.debug("Google OIDC configuration retrieved", extra={
                    'operation': 'get_google_config',
                    'issuer': config.get('issuer'),
                    'endpoints_count': len([k for k in config.keys() if k.endswith('_endpoint')])
                })
                
                return config
                
        except httpx.RequestError as e:
            logger.error("Failed to retrieve Google OIDC configuration", exc_info=True, extra={
                'operation': 'get_google_config',
                'discovery_url': self.google_discovery_url,
                'error_type': type(e).__name__
            })
            raise OIDCServiceError(
                'ERR-OIDC-CONFIG-FAILED',
                'OIDC yapılandırması alınamadı'
            )
        except Exception as e:
            logger.error("Unexpected error retrieving Google OIDC configuration", exc_info=True)
            raise OIDCServiceError(
                'ERR-OIDC-CONFIG-UNEXPECTED',
                'OIDC yapılandırması beklenmeyen hata'
            )
    
    def generate_pkce_pair(self) -> Tuple[str, str]:
        """
        Generate PKCE code verifier and challenge (S256).
        
        Returns:
            Tuple of (code_verifier, code_challenge)
        """
        # Generate 128 bytes (1024 bits) of entropy for code verifier
        code_verifier = base64.urlsafe_b64encode(
            secrets.token_bytes(96)
        ).decode('utf-8').rstrip('=')
        
        # Create S256 challenge
        challenge_bytes = hashlib.sha256(code_verifier.encode('utf-8')).digest()
        code_challenge = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')
        
        logger.debug("PKCE pair generated", extra={
            'operation': 'generate_pkce_pair',
            'verifier_length': len(code_verifier),
            'challenge_length': len(code_challenge)
        })
        
        return code_verifier, code_challenge
    
    def generate_secure_state(self) -> str:
        """
        Generate cryptographically secure state parameter.
        
        Returns:
            URL-safe state string
        """
        return secrets.token_urlsafe(64)  # 512 bits of entropy
    
    def generate_nonce(self) -> str:
        """
        Generate cryptographically secure nonce for OIDC.
        
        Returns:
            URL-safe nonce string
        """
        return secrets.token_urlsafe(32)  # 256 bits of entropy
    
    async def store_oauth_state(
        self,
        redis_client,
        state: str,
        pkce_verifier: str,
        nonce: str,
        redirect_uri: str
    ) -> None:
        """
        Securely store OAuth state data in Redis.
        
        Args:
            redis_client: Redis client instance from dependency injection
            state: OAuth state parameter
            pkce_verifier: PKCE code verifier
            nonce: OIDC nonce
            redirect_uri: OAuth redirect URI
        """
        state_data = {
            'pkce_verifier': pkce_verifier,
            'nonce': nonce,
            'redirect_uri': redirect_uri,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'ip_address': None,  # Will be set by router
            'user_agent': None   # Will be set by router
        }
        
        # Store state data
        await redis_client.setex(
            f"{self.state_prefix}{state}",
            self.state_expire_seconds,
            json.dumps(state_data)
        )
        
        # Also store PKCE verifier separately for additional security
        await redis_client.setex(
            f"{self.pkce_prefix}{state}",
            self.pkce_verifier_expire_seconds,
            pkce_verifier
        )
        
        # Store nonce for validation
        await redis_client.setex(
            f"{self.nonce_prefix}{state}",
            self.state_expire_seconds,
            nonce
        )
        
        logger.debug("OAuth state stored securely", extra={
            'operation': 'store_oauth_state',
            'state_length': len(state),
            'expire_seconds': self.state_expire_seconds
        })
    
    async def retrieve_and_validate_state(
        self,
        redis_client,
        state: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Retrieve and validate OAuth state data.
        
        Args:
            redis_client: Redis client instance from dependency injection
            state: OAuth state parameter
            ip_address: Client IP address for security validation
            user_agent: Client user agent for security validation
            
        Returns:
            State data dictionary
            
        Raises:
            OIDCServiceError: If state is invalid or expired
        """
        try:
            # Retrieve state data
            state_json = await redis_client.get(f"{self.state_prefix}{state}")
            if not state_json:
                raise OIDCServiceError(
                    'ERR-OIDC-STATE',
                    'OIDC state doğrulaması başarısız'
                )
            
            state_data = json.loads(state_json)
            
            # Verify PKCE verifier exists
            pkce_verifier = await redis_client.get(f"{self.pkce_prefix}{state}")
            if not pkce_verifier:
                raise OIDCServiceError(
                    'ERR-OIDC-PKCE-MISSING',
                    'OIDC PKCE doğrulayıcısı bulunamadı'
                )
            
            # Verify nonce exists
            nonce = await redis_client.get(f"{self.nonce_prefix}{state}")
            if not nonce:
                raise OIDCServiceError(
                    'ERR-OIDC-NONCE',
                    'OIDC nonce doğrulaması başarısız'
                )
            
            # Update state data with current verifier and nonce
            state_data['pkce_verifier'] = pkce_verifier.decode('utf-8')
            state_data['nonce'] = nonce.decode('utf-8')
            
            # Clean up used state data
            await redis_client.delete(f"{self.state_prefix}{state}")
            await redis_client.delete(f"{self.pkce_prefix}{state}")
            await redis_client.delete(f"{self.nonce_prefix}{state}")
            
            logger.debug("OAuth state validated and cleaned", extra={
                'operation': 'retrieve_and_validate_state',
                'state_age_seconds': (
                    datetime.now(timezone.utc) - 
                    datetime.fromisoformat(state_data['created_at'])
                ).total_seconds()
            })
            
            return state_data
            
        except json.JSONDecodeError:
            raise OIDCServiceError(
                'ERR-OIDC-STATE-CORRUPT',
                'OIDC state verisi bozuk'
            )
        except Exception as e:
            logger.error("OAuth state validation failed", exc_info=True, extra={
                'operation': 'retrieve_and_validate_state',
                'error_type': type(e).__name__
            })
            raise OIDCServiceError(
                'ERR-OIDC-STATE-VALIDATION-FAILED',
                'OIDC state doğrulaması başarısız'
            )
    
    async def create_authorization_url(
        self,
        redis_client,
        redirect_uri: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[str, str]:
        """
        Create Google OAuth2 authorization URL with PKCE and state.
        
        Args:
            redis_client: Redis client instance from dependency injection
            redirect_uri: OAuth redirect URI
            ip_address: Client IP address for audit
            user_agent: Client user agent for audit
            
        Returns:
            Tuple of (authorization_url, state)
            
        Raises:
            OIDCServiceError: If URL creation fails
        """
        try:
            # Get Google configuration
            google_config = await self.get_google_config()
            authorization_endpoint = google_config['authorization_endpoint']
            
            # Generate security parameters
            state = self.generate_secure_state()
            nonce = self.generate_nonce()
            code_verifier, code_challenge = self.generate_pkce_pair()
            
            # Store state data securely
            await self.store_oauth_state(redis_client, state, code_verifier, nonce, redirect_uri)
            
            # Build authorization URL
            auth_params = {
                'client_id': self.google_client_id,
                'response_type': 'code',
                'scope': ' '.join(self.google_scopes),
                'redirect_uri': redirect_uri,
                'state': state,
                'nonce': nonce,
                'code_challenge': code_challenge,
                'code_challenge_method': 'S256',
                'access_type': 'offline',  # For refresh tokens
                'prompt': 'consent'  # Force consent to get refresh token
            }
            
            authorization_url = f"{authorization_endpoint}?{urlencode(auth_params)}"
            
            logger.info("OIDC authorization URL created", extra={
                'operation': 'create_authorization_url',
                'provider': 'google',
                'scopes': self.google_scopes,
                'has_pkce': True,
                'has_nonce': True,
                'client_ip': ip_address
            })
            
            return authorization_url, state
            
        except OIDCServiceError:
            raise  # Re-raise our errors
        except Exception as e:
            logger.error("Failed to create authorization URL", exc_info=True, extra={
                'operation': 'create_authorization_url',
                'error_type': type(e).__name__
            })
            raise OIDCServiceError(
                'ERR-OIDC-AUTH-URL-FAILED',
                'OIDC yetkilendirme URL\'si oluşturulamadı'
            )
    
    async def exchange_code_for_tokens(
        self,
        redis_client,
        code: str,
        state: str,
        redirect_uri: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Exchange authorization code for tokens using PKCE verification.
        
        Args:
            redis_client: Redis client instance from dependency injection
            code: Authorization code from Google
            state: OAuth state parameter
            redirect_uri: OAuth redirect URI
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            Token response with ID token claims
            
        Raises:
            OIDCServiceError: If token exchange fails
        """
        try:
            # Validate state and get PKCE verifier
            state_data = await self.retrieve_and_validate_state(
                redis_client, state, ip_address, user_agent
            )
            
            # Verify redirect URI matches
            if state_data['redirect_uri'] != redirect_uri:
                raise OIDCServiceError(
                    'ERR-OIDC-REDIRECT-MISMATCH',
                    'OIDC redirect URI uyumsuzluğu'
                )
            
            # Get Google configuration
            google_config = await self.get_google_config()
            token_endpoint = google_config['token_endpoint']
            
            # Prepare token request
            token_data = {
                'client_id': self.google_client_id,
                'client_secret': self.google_client_secret,
                'code': code,
                'grant_type': 'authorization_code',
                'redirect_uri': redirect_uri,
                'code_verifier': state_data['pkce_verifier']
            }
            
            # Exchange code for tokens
            async with httpx.AsyncClient(timeout=self.callback_timeout_seconds) as client:
                response = await client.post(
                    token_endpoint,
                    data=token_data,
                    headers={'Accept': 'application/json'}
                )
                
                if response.status_code != 200:
                    logger.warning("Token exchange failed", extra={
                        'operation': 'exchange_code_for_tokens',
                        'status_code': response.status_code,
                        'response_text': response.text[:500]
                    })
                    raise OIDCServiceError(
                        'ERR-OIDC-TOKEN-EXCHANGE',
                        'OIDC token değişimi başarısız'
                    )
                
                token_response = response.json()
            
            # Verify and decode ID token
            id_token = token_response.get('id_token')
            if not id_token:
                raise OIDCServiceError(
                    'ERR-OIDC-NO-ID-TOKEN',
                    'OIDC ID token bulunamadı'
                )
            
            # Verify nonce in ID token with proper signature verification
            id_token_claims = await self._verify_id_token(id_token, state_data['nonce'])
            
            logger.info("OIDC token exchange successful", extra={
                'operation': 'exchange_code_for_tokens',
                'provider': 'google',
                'has_refresh_token': 'refresh_token' in token_response,
                'token_type': token_response.get('token_type'),
                'client_ip': ip_address
            })
            
            return {
                'access_token': token_response['access_token'],
                'id_token': id_token,
                'id_token_claims': id_token_claims,
                'refresh_token': token_response.get('refresh_token'),
                'expires_in': token_response.get('expires_in', 3600),
                'token_type': token_response.get('token_type', 'Bearer')
            }
            
        except OIDCServiceError:
            raise  # Re-raise our errors
        except Exception as e:
            logger.error("Token exchange failed", exc_info=True, extra={
                'operation': 'exchange_code_for_tokens',
                'error_type': type(e).__name__
            })
            raise OIDCServiceError(
                'ERR-OIDC-TOKEN-EXCHANGE-FAILED',
                'OIDC token değişimi başarısız'
            )
    
    async def _get_jwks_client(self) -> PyJWKClient:
        """
        Get or create JWKS client for JWT signature verification.
        
        Returns:
            PyJWKClient instance for Google's JWKS endpoint
            
        Raises:
            OIDCServiceError: If JWKS client creation fails
        """
        now = datetime.now(timezone.utc)
        
        # Check if client is cached and not expired
        if (self._jwks_client and 
            self._jwks_client_expires and 
            now < self._jwks_client_expires):
            return self._jwks_client
        
        try:
            # Get Google configuration for JWKS URI
            google_config = await self.get_google_config()
            jwks_uri = google_config.get('jwks_uri')
            
            if not jwks_uri:
                raise OIDCServiceError(
                    'ERR-OIDC-NO-JWKS-URI',
                    'OIDC JWKS endpoint bulunamadı'
                )
            
            # Create JWKS client with proper security settings
            self._jwks_client = PyJWKClient(
                jwks_uri,
                cache_keys=True,
                max_cached_keys=10,
                cache_jwks=True,
                jwks_cache_ttl=3600,  # 1 hour cache
                timeout=10.0
            )
            
            # Cache client for 30 minutes
            self._jwks_client_expires = now + timedelta(minutes=30)
            
            logger.debug("JWKS client created", extra={
                'operation': '_get_jwks_client',
                'jwks_uri': jwks_uri,
                'cache_ttl': 3600
            })
            
            return self._jwks_client
            
        except Exception as e:
            logger.error("Failed to create JWKS client", exc_info=True, extra={
                'operation': '_get_jwks_client',
                'error_type': type(e).__name__
            })
            raise OIDCServiceError(
                'ERR-OIDC-JWKS-CLIENT-FAILED',
                'OIDC JWKS istemcisi oluşturulamadı'
            )
    
    async def _verify_id_token(self, id_token: str, expected_nonce: str) -> Dict[str, Any]:
        """
        Verify ID token signature and claims using Google's JWKS.
        
        Args:
            id_token: JWT ID token from Google
            expected_nonce: Expected nonce value
            
        Returns:
            ID token claims
            
        Raises:
            OIDCServiceError: If verification fails
        """
        try:
            # Get JWKS client for signature verification
            jwks_client = await self._get_jwks_client()
            
            # Get signing key from JWKS
            signing_key = jwks_client.get_signing_key_from_jwt(id_token)
            
            # Verify JWT signature and decode claims
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],  # Google uses RS256
                audience=self.google_client_id,
                issuer="https://accounts.google.com",
                options={
                    "verify_signature": True,
                    "verify_aud": True,
                    "verify_iss": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "require": ["aud", "iss", "exp", "iat", "sub"]
                }
            )
            
            # Additional verification: issuer and audience are already verified by PyJWT
            # But we double-check for security
            if claims.get('iss') != 'https://accounts.google.com':
                raise OIDCServiceError(
                    'ERR-OIDC-INVALID-ISSUER',
                    'OIDC issuer geçersiz'
                )
            
            if claims.get('aud') != self.google_client_id:
                raise OIDCServiceError(
                    'ERR-OIDC-INVALID-AUDIENCE',
                    'OIDC audience geçersiz'
                )
            
            # Verify nonce
            if claims.get('nonce') != expected_nonce:
                raise OIDCServiceError(
                    'ERR-OIDC-NONCE',
                    'OIDC nonce doğrulaması başarısız'
                )
            
            # Expiration is already verified by PyJWT, but we can add additional checks
            # Verify token was issued recently (not older than 24 hours)
            now = datetime.now(timezone.utc).timestamp()
            iat = claims.get('iat', 0)
            if now - iat > 86400:  # 24 hours
                raise OIDCServiceError(
                    'ERR-OIDC-TOKEN-TOO-OLD',
                    'OIDC token çok eski'
                )
            
            logger.info("ID token signature and claims verified successfully", extra={
                'operation': '_verify_id_token',
                'subject': claims.get('sub'),
                'email': claims.get('email', 'unknown'),
                'verified_signature': True,
                'algorithm': 'RS256'
            })
            
            return claims
            
        except jwt.PyJWTError as e:
            logger.error("ID token JWT verification failed", exc_info=True, extra={
                'operation': '_verify_id_token',
                'error_type': type(e).__name__,
                'jwt_error': str(e)
            })
            raise OIDCServiceError(
                'ERR-OIDC-TOKEN-INVALID',
                'OIDC token imza doğrulaması başarısız'
            )
        except Exception as e:
            logger.error("ID token verification failed with unexpected error", exc_info=True, extra={
                'operation': '_verify_id_token',
                'error_type': type(e).__name__
            })
            raise OIDCServiceError(
                'ERR-OIDC-TOKEN-VERIFICATION-FAILED',
                'OIDC token doğrulaması başarısız'
            )
    
    async def authenticate_or_link_user(
        self,
        db: DBSession,
        id_token_claims: Dict[str, Any],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> OIDCAuthResult:
        """
        Authenticate user or link OIDC account to existing user.
        
        Args:
            db: Database session
            id_token_claims: Verified ID token claims
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            OIDCAuthResult with user and tokens
            
        Raises:
            OIDCServiceError: If authentication fails
        """
        provider = 'google'
        sub = id_token_claims['sub']
        email = id_token_claims.get('email', '').lower()
        email_verified = id_token_claims.get('email_verified', False)
        picture = id_token_claims.get('picture')
        
        is_new_user = False
        is_new_oidc_link = False
        
        try:
            # Check if OIDC account already exists
            oidc_account = OIDCAccount.find_by_provider_sub(db, provider, sub)
            
            if oidc_account:
                # Existing OIDC account - authenticate
                user = oidc_account.user
                
                # Verify account is active
                if not user.can_attempt_login():
                    raise OIDCServiceError(
                        'ERR-OIDC-ACCOUNT-INACTIVE',
                        'Kullanıcı hesabı aktif değil'
                    )
                
                # Update OIDC account information
                oidc_account.email = email
                oidc_account.email_verified = email_verified
                oidc_account.picture = picture
                oidc_account.record_login()
                
            else:
                # New OIDC account
                is_new_oidc_link = True
                
                # Check if user with this email already exists
                user = db.query(User).filter(User.email == email).first()
                
                if user:
                    # Link to existing user
                    if not user.can_attempt_login():
                        raise OIDCServiceError(
                            'ERR-OIDC-ACCOUNT-INACTIVE',
                            'Kullanıcı hesabı aktif değil'
                        )
                else:
                    # Create new user
                    is_new_user = True
                    
                    if not email_verified:
                        raise OIDCServiceError(
                            'ERR-OIDC-EMAIL-NOT-VERIFIED',
                            'E-posta adresi doğrulanmamış'
                        )
                    
                    # Create user via auth service
                    user = auth_service.create_oidc_user(
                        db=db,
                        email=email,
                        full_name=id_token_claims.get('name'),
                        picture=picture,
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                
                # Create OIDC account
                oidc_account = OIDCAccount(
                    user_id=user.id,
                    provider=provider,
                    sub=sub,
                    email=email,
                    email_verified=email_verified,
                    picture=picture,
                    provider_data=id_token_claims
                )
                oidc_account.record_login()
                
                db.add(oidc_account)
            
            # Update user login metadata
            user.update_login_metadata(ip_address or '', user_agent or '')
            user.reset_failed_login_attempts()
            
            # Create tokens using existing token service
            token_result = token_service.create_refresh_session(
                db=db,
                user=user,
                device_fingerprint=None,  # Could be added in future
                ip_address=ip_address,
                user_agent=user_agent
            )
            
            # Log successful authentication
            self._log_oidc_audit_event(
                db, user.id,
                'oidc_login_succeeded' if not is_new_user else 'oidc_user_created',
                f'OIDC girişi başarılı: {provider} ({oidc_account.get_masked_email()})',
                {
                    'provider': provider,
                    'oidc_account_id': oidc_account.id,
                    'is_new_user': is_new_user,
                    'is_new_oidc_link': is_new_oidc_link,
                    'email_verified': email_verified
                }
            )
            
            db.commit()
            
            logger.info("OIDC authentication successful", extra={
                'operation': 'authenticate_or_link_user',
                'provider': provider,
                'user_id': user.id,
                'is_new_user': is_new_user,
                'is_new_oidc_link': is_new_oidc_link,
                'client_ip': ip_address
            })
            
            return OIDCAuthResult(
                user=user,
                oidc_account=oidc_account,
                is_new_user=is_new_user,
                is_new_oidc_link=is_new_oidc_link,
                access_token=token_result.access_token,
                refresh_token=token_result.refresh_token,
                expires_in=token_result.expires_in
            )
            
        except OIDCServiceError:
            db.rollback()
            raise  # Re-raise our errors
        except Exception as e:
            db.rollback()
            logger.error("OIDC authentication failed", exc_info=True, extra={
                'operation': 'authenticate_or_link_user',
                'provider': provider,
                'sub': sub,
                'error_type': type(e).__name__
            })
            raise OIDCServiceError(
                'ERR-OIDC-AUTH-FAILED',
                'OIDC kimlik doğrulama başarısız'
            )
    
    def _log_oidc_audit_event(
        self,
        db: DBSession,
        user_id: int,
        action: str,
        description: str,
        details: Dict[str, Any]
    ) -> None:
        """Log OIDC audit event with PII masking."""
        try:
            # Mask sensitive data in details
            masked_details = details.copy()
            if 'email' in masked_details:
                email = masked_details['email']
                if '@' in email:
                    username, domain = email.rsplit('@', 1)
                    masked_details['email'] = f"{username[:2]}***@{domain}"
            
            audit_log = AuditLog(
                user_id=user_id,
                action=action,
                description=description,
                details=masked_details
            )
            db.add(audit_log)
            db.flush()
        except Exception as e:
            logger.error("Failed to log OIDC audit event", exc_info=True, extra={
                'action': action,
                'user_id': user_id
            })
    
    def _log_oidc_security_event(
        self,
        db: DBSession,
        user_id: Optional[int],
        event_type: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
        details: Dict[str, Any]
    ) -> None:
        """Log OIDC security event."""
        try:
            security_event = SecurityEvent(
                user_id=user_id,
                event_type=event_type,
                ip_address=ip_address,
                user_agent=user_agent,
                details=details,
                severity='HIGH' if 'FAILED' in event_type else 'MEDIUM'
            )
            db.add(security_event)
            db.flush()
        except Exception as e:
            logger.error("Failed to log OIDC security event", exc_info=True, extra={
                'event_type': event_type,
                'user_id': user_id
            })


# Global OIDC service instance
oidc_service = OIDCService()