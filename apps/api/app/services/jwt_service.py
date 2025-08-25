"""
Ultra Enterprise JWT Service for Task 3.3

This service implements banking-level JWT token management with:
- PyJWT 2.8 with crypto support for secure token signing
- Proper JWT claims: sub (user_id), role, scopes, sid (session_id), iat, exp
- 30-minute access tokens with cryptographic security
- Session ID correlation for token revocation
- Enterprise error handling with Turkish localization
- Security audit logging for token operations
"""

import jwt
import secrets
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List, Set
from enum import Enum

from fastapi import HTTPException, status
from sqlalchemy.orm import Session as DBSession

from ..models.user import User
from ..models.session import Session
from ..models.audit_log import AuditLog
from ..core.logging import get_logger
from ..config import settings

logger = get_logger(__name__)


class JWTErrorCode(str, Enum):
    """JWT-specific error codes for Turkish localization."""
    
    TOKEN_INVALID = "ERR-TOKEN-INVALID"
    TOKEN_EXPIRED = "ERR-TOKEN-EXPIRED"
    TOKEN_REVOKED = "ERR-TOKEN-REVOKED"
    TOKEN_MALFORMED = "ERR-TOKEN-MALFORMED"
    TOKEN_MISSING_CLAIMS = "ERR-TOKEN-MISSING-CLAIMS"
    TOKEN_INVALID_SIGNATURE = "ERR-TOKEN-INVALID-SIGNATURE"
    TOKEN_WRONG_ALGORITHM = "ERR-TOKEN-WRONG-ALGORITHM"
    SESSION_NOT_FOUND = "ERR-SESSION-NOT-FOUND"


class JWTError(Exception):
    """Base JWT service error with Turkish localization."""
    
    def __init__(self, code: JWTErrorCode, message: str, details: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class JWTClaims:
    """JWT claims structure for type safety."""
    
    def __init__(
        self,
        sub: str,  # User ID as string
        role: str,
        scopes: List[str],
        sid: str,  # Session ID as string
        iat: int,  # Issued at timestamp
        exp: int,  # Expiration timestamp
        iss: str = None,
        aud: str = None,
        jti: str = None,  # JWT ID for tracking
        license_id: str = None,  # License ID for Task 7.1
        tenant_id: str = None  # Tenant ID for Task 7.1
    ):
        self.sub = sub
        self.role = role
        self.scopes = scopes
        self.sid = sid
        self.iat = iat
        self.exp = exp
        self.iss = iss or settings.jwt_issuer
        self.aud = aud or settings.jwt_audience
        self.jti = jti or str(uuid.uuid4())
        self.license_id = license_id  # Task 7.1: License tracking
        self.tenant_id = tenant_id  # Task 7.1: Multi-tenancy support
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert claims to dictionary for JWT encoding."""
        result = {
            'sub': self.sub,
            'role': self.role,
            'scopes': self.scopes,
            'sid': self.sid,
            'iat': self.iat,
            'exp': self.exp,
            'iss': self.iss,
            'aud': self.aud,
            'jti': self.jti
        }
        # Task 7.1: Include optional claims if present
        if self.license_id:
            result['license_id'] = self.license_id
        if self.tenant_id:
            result['tenant_id'] = self.tenant_id
        return result
    
    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "JWTClaims":
        """Create claims from JWT payload dictionary."""
        return cls(
            sub=payload.get('sub'),
            role=payload.get('role'),
            scopes=payload.get('scopes', []),
            sid=payload.get('sid'),
            iat=payload.get('iat'),
            exp=payload.get('exp'),
            iss=payload.get('iss'),
            aud=payload.get('aud'),
            jti=payload.get('jti'),
            license_id=payload.get('license_id'),  # Task 7.1
            tenant_id=payload.get('tenant_id')  # Task 7.1
        )


class JWTService:
    """Ultra enterprise JWT token management service with banking-level security."""
    
    def __init__(self):
        # Use separate JWT secret or fallback to main secret
        self.secret_key = settings.jwt_secret_key or settings.secret_key
        self.algorithm = settings.jwt_algorithm
        self.access_token_expire_minutes = settings.jwt_access_token_expire_minutes
        self.issuer = settings.jwt_issuer
        self.audience = settings.jwt_audience
        
        # Validate configuration
        if len(self.secret_key) < 32:
            raise ValueError("JWT secret key must be at least 32 characters for security")
        
        # Algorithm validation for security
        if self.algorithm not in ['HS256', 'HS384', 'HS512', 'RS256', 'RS384', 'RS512']:
            raise ValueError(f"Unsupported JWT algorithm: {self.algorithm}")
    
    def create_access_token(
        self,
        user: User,
        session: Session,
        scopes: Optional[List[str]] = None
    ) -> str:
        """
        Create JWT access token with enterprise security claims.
        
        Args:
            user: User object
            session: Session object for correlation
            scopes: Optional permission scopes
            
        Returns:
            Signed JWT access token
            
        Raises:
            JWTError: If token creation fails
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Default scopes based on user role
            if scopes is None:
                scopes = self._get_default_scopes_for_role(user.role)
            
            # Create timestamp claims
            now = datetime.now(timezone.utc)
            iat = int(now.timestamp())
            exp = int((now + timedelta(minutes=self.access_token_expire_minutes)).timestamp())
            
            # Build claims
            claims = JWTClaims(
                sub=str(user.id),
                role=user.role.value if hasattr(user.role, 'value') else str(user.role),
                scopes=scopes,
                sid=str(session.id),
                iat=iat,
                exp=exp,
                iss=self.issuer,
                aud=self.audience
            )
            
            # Encode JWT with PyJWT 2.8
            token = jwt.encode(
                claims.to_dict(),
                self.secret_key,
                algorithm=self.algorithm
            )
            
            elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            
            logger.info("JWT access token created", extra={
                'operation': 'jwt_create_access_token',
                'user_id': user.id,
                'session_id': str(session.id),
                'token_id': claims.jti,
                'scopes': scopes,
                'expires_in_minutes': self.access_token_expire_minutes,
                'elapsed_ms': elapsed_ms
            })
            
            return token
            
        except Exception as e:
            logger.error("JWT access token creation failed", exc_info=True, extra={
                'operation': 'jwt_create_access_token',
                'user_id': user.id,
                'session_id': str(session.id),
                'error_type': type(e).__name__
            })
            raise JWTError(
                JWTErrorCode.TOKEN_INVALID,
                "JWT token oluşturma başarısız",
                {'error_type': type(e).__name__}
            )
    
    def create_test_token(self, claims: dict) -> str:
        """
        SECURITY WARNING: This method MUST NOT be used in production environments.
        It bypasses normal validation and database checks, and can create arbitrary JWT tokens.
        Use only for testing purposes. Misuse can lead to severe security vulnerabilities.
        
        Create a JWT token with custom claims for testing purposes.
        
        Args:
            claims: Dictionary of JWT claims
            
        Returns:
            Encoded JWT token string
            
        CRITICAL: This method:
        - Bypasses all authentication and authorization checks
        - Does not validate user existence or credentials
        - Can create tokens with any arbitrary claims or permissions
        - Completely circumvents session management and audit logging
        - Should NEVER be exposed through any API endpoint
        - Must be disabled or removed in production builds
        """
        # Runtime production check
        import os
        from ..config import settings
        
        # Check for production environment indicators
        # FIXED: DEV_AUTH_BYPASS logic was inverted
        # When DEV_AUTH_BYPASS=true, it's development mode (NOT production)
        is_production = any([
            os.getenv('ENV', '').lower() in ['production', 'prod'],
            os.getenv('ENVIRONMENT', '').lower() in ['production', 'prod'],
            settings.env.lower() in ['production', 'prod'],
            os.getenv('DEV_AUTH_BYPASS', 'false').lower() == 'false'  # Fixed: == 'false' means production
        ])
        
        if is_production:
            logger.critical(
                "SECURITY VIOLATION: Attempted to use create_test_token in production environment",
                extra={
                    'operation': 'create_test_token_blocked',
                    'env': settings.env,
                    'dev_auth_bypass': os.getenv('DEV_AUTH_BYPASS', 'false')
                }
            )
            raise RuntimeError(
                "SECURITY: create_test_token is disabled in production environment. "
                "This method must only be used for testing."
            )
        
        # Log warning even in development
        logger.warning(
            "Creating test JWT token - This should NEVER occur in production",
            extra={
                'operation': 'create_test_token',
                'claims_keys': list(claims.keys()),
                'env': settings.env
            }
        )
        
        # Encode JWT with PyJWT 2.8
        token = jwt.encode(
            claims,
            self.secret_key,
            algorithm=self.algorithm
        )
        
        return token
    
    def verify_access_token(
        self,
        token: str,
        db: DBSession
    ) -> JWTClaims:
        """
        Verify and decode JWT access token with session validation.
        
        Args:
            token: JWT access token to verify
            db: Database session for validation
            
        Returns:
            Decoded JWT claims
            
        Raises:
            JWTError: If token verification fails
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Decode JWT with PyJWT 2.8
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                audience=self.audience,
                options={
                    "verify_signature": True,
                    "verify_exp": True,
                    "verify_iat": True,
                    "verify_iss": True,
                    "verify_aud": True,
                    "require": ["sub", "role", "sid", "iat", "exp"]
                }
            )
            
            # Parse claims
            claims = JWTClaims.from_dict(payload)
            
            # Validate required claims
            if not all([claims.sub, claims.role, claims.sid]):
                raise JWTError(
                    JWTErrorCode.TOKEN_MISSING_CLAIMS,
                    "Token'da gerekli bilgiler eksik"
                )
            
            # Validate session exists and is active
            session = db.query(Session).filter(
                Session.id == uuid.UUID(claims.sid),
                Session.user_id == int(claims.sub)
            ).first()
            
            if not session:
                raise JWTError(
                    JWTErrorCode.SESSION_NOT_FOUND,
                    "Token'a bağlı oturum bulunamadı"
                )
            
            if not session.is_active:
                raise JWTError(
                    JWTErrorCode.TOKEN_REVOKED,
                    "Token iptal edilmiş veya süresi dolmuş"
                )
            
            # Note: Session.update_last_used() removed to eliminate database side effect
            # in verification method. Session last_used should only be updated during
            # login/refresh operations, not during every JWT verification.
            
            elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            
            logger.info("JWT access token verified", extra={
                'operation': 'jwt_verify_access_token',
                'user_id': int(claims.sub),
                'session_id': claims.sid,
                'token_id': claims.jti,
                'elapsed_ms': elapsed_ms
            })
            
            return claims
            
        except jwt.ExpiredSignatureError:
            raise JWTError(
                JWTErrorCode.TOKEN_EXPIRED,
                "Token'ın süresi dolmuş"
            )
        except jwt.InvalidSignatureError:
            raise JWTError(
                JWTErrorCode.TOKEN_INVALID_SIGNATURE,
                "Token imzası geçersiz"
            )
        except jwt.InvalidAlgorithmError:
            raise JWTError(
                JWTErrorCode.TOKEN_WRONG_ALGORITHM,
                "Token algoritması desteklenmiyor"
            )
        except jwt.InvalidTokenError as e:
            raise JWTError(
                JWTErrorCode.TOKEN_MALFORMED,
                "Token formatı geçersiz",
                {'jwt_error': str(e)}
            )
        except JWTError:
            raise  # Re-raise our custom errors
        except Exception as e:
            logger.error("JWT token verification failed", exc_info=True, extra={
                'operation': 'jwt_verify_access_token',
                'error_type': type(e).__name__
            })
            raise JWTError(
                JWTErrorCode.TOKEN_INVALID,
                "Token doğrulama başarısız",
                {'error_type': type(e).__name__}
            )
    
    def revoke_tokens_for_session(
        self,
        db: DBSession,
        session_id: uuid.UUID,
        reason: str = "session_revoked"
    ) -> None:
        """
        Revoke all JWT tokens for a session by revoking the session.
        
        Args:
            db: Database session
            session_id: Session ID to revoke
            reason: Revocation reason for audit
        """
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session and session.is_active:
                session.revoke(reason)
                db.commit()
                
                logger.info("JWT tokens revoked for session", extra={
                    'operation': 'jwt_revoke_session_tokens',
                    'session_id': str(session_id),
                    'user_id': session.user_id,
                    'reason': reason
                })
        except Exception as e:
            db.rollback()
            logger.error("JWT token revocation failed", exc_info=True, extra={
                'operation': 'jwt_revoke_session_tokens',
                'session_id': str(session_id),
                'error_type': type(e).__name__
            })
            raise
    
    def revoke_all_tokens_for_user(
        self,
        db: DBSession,
        user_id: int,
        reason: str = "logout_all"
    ) -> int:
        """
        Revoke all JWT tokens for a user by revoking all their sessions.
        
        Args:
            db: Database session
            user_id: User ID
            reason: Revocation reason
            
        Returns:
            Number of sessions revoked
        """
        try:
            # Get all active sessions for user
            active_sessions = db.query(Session).filter(
                Session.user_id == user_id,
                Session.revoked_at.is_(None)
            ).all()
            
            revoked_count = 0
            for session in active_sessions:
                session.revoke(reason)
                revoked_count += 1
            
            db.commit()
            
            logger.info("All JWT tokens revoked for user", extra={
                'operation': 'jwt_revoke_all_user_tokens',
                'user_id': user_id,
                'sessions_revoked': revoked_count,
                'reason': reason
            })
            
            return revoked_count
            
        except Exception as e:
            db.rollback()
            logger.error("User JWT token revocation failed", exc_info=True, extra={
                'operation': 'jwt_revoke_all_user_tokens',
                'user_id': user_id,
                'error_type': type(e).__name__
            })
            raise
    
    def _get_default_scopes_for_role(self, role: str) -> List[str]:
        """Get default permission scopes for user role."""
        role_scopes = {
            'admin': ['read', 'write', 'delete', 'admin'],
            'engineer': ['read', 'write'],
            'viewer': ['read'],
            'guest': ['read']
        }
        
        # Handle both string and enum role types
        role_str = role.value if hasattr(role, 'value') else str(role).lower()
        return role_scopes.get(role_str, ['read'])
    
    def get_token_claims_without_verification(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Decode JWT token without verification for debugging/logging.
        WARNING: Only use for non-security purposes!
        
        Args:
            token: JWT token to decode
            
        Returns:
            Token claims or None if malformed
        """
        try:
            return jwt.decode(token, options={"verify_signature": False})
        except Exception:
            return None


# Global JWT service instance
jwt_service = JWTService()