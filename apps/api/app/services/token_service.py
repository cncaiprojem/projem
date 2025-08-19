"""
Ultra Enterprise Token Service for Task 3.3

This service implements banking-level refresh token management with:
- 256-bit cryptographically secure opaque refresh tokens
- 7-day TTL with automatic rotation on each use
- Refresh token reuse detection with security response
- Session chain revocation for compromise detection
- HttpOnly cookie security with all enterprise attributes
- Complete audit trail for forensic analysis
"""

import secrets
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
import uuid

from fastapi import Response, Request, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import and_, or_

from ..models.user import User
from ..models.session import Session
from ..models.audit_log import AuditLog
from ..models.security_event import SecurityEvent
from ..core.logging import get_logger
from ..config import settings
from .session_service import SessionService, SessionSecurityError

logger = get_logger(__name__)


class TokenServiceError(Exception):
    """Base token service error with Turkish localization."""

    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class RefreshTokenResult:
    """Result of refresh token operation."""

    def __init__(self, session: Session, refresh_token: str, access_token: str, expires_in: int):
        self.session = session
        self.refresh_token = refresh_token
        self.access_token = access_token
        self.expires_in = expires_in


class TokenService:
    """Ultra enterprise refresh token management with banking-level security."""

    def __init__(self):
        self.session_service = SessionService()

        # Refresh token configuration
        self.refresh_token_length = settings.refresh_token_length  # 64 bytes = 512 bits
        self.refresh_token_expire_days = settings.jwt_refresh_token_expire_days

        # Cookie configuration
        self.cookie_name = settings.refresh_token_cookie_name
        self.cookie_domain = settings.refresh_token_cookie_domain
        self.cookie_secure = settings.refresh_token_cookie_secure and settings.env != "development"
        self.cookie_samesite = settings.refresh_token_cookie_samesite
        self.cookie_max_age = self.refresh_token_expire_days * 24 * 60 * 60  # Convert to seconds

        # Security configuration
        self.max_rotation_chain = 50  # Prevent infinite chains
        self.reuse_detection_window_hours = 24  # Window for detecting reuse attacks

        # Token secret for HMAC (separate from JWT secret for additional security)
        self.token_secret = getattr(settings, "REFRESH_TOKEN_SECRET", settings.secret_key)

    def generate_refresh_token(self) -> str:
        """
        Generate cryptographically secure 256-bit refresh token.

        Returns:
            Base64URL-encoded secure token (512 bits of entropy)
        """
        # Generate 64 bytes (512 bits) of cryptographically secure random data
        token_bytes = secrets.token_bytes(self.refresh_token_length)

        # Encode as base64url for URL-safe transport
        token = secrets.token_urlsafe(self.refresh_token_length)

        logger.debug(
            "Refresh token generated",
            extra={
                "operation": "generate_refresh_token",
                "token_length": len(token),
                "entropy_bits": self.refresh_token_length * 8,
            },
        )

        return token

    def hash_refresh_token(self, token: str) -> str:
        """
        Hash refresh token using SHA512/HMAC for secure storage.

        Args:
            token: Plaintext refresh token

        Returns:
            Hex-encoded SHA512 HMAC hash (128 characters)
        """
        # Use HMAC-SHA512 for additional security
        hmac_obj = hmac.new(
            self.token_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha512
        )

        return hmac_obj.hexdigest()

    def create_refresh_session(
        self,
        db: DBSession,
        user: User,
        device_fingerprint: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> RefreshTokenResult:
        """
        Create new session with refresh token.

        Args:
            db: Database session
            user: User object
            device_fingerprint: Device fingerprint
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            RefreshTokenResult with session and tokens

        Raises:
            TokenServiceError: If creation fails
        """
        start_time = datetime.now(timezone.utc)

        try:
            # Create session using existing session service
            session, refresh_token = self.session_service.create_session(
                db=db,
                user_id=user.id,
                device_fingerprint=device_fingerprint,
                ip_address=ip_address,
                user_agent=user_agent,
                expires_in_hours=self.refresh_token_expire_days * 24,
            )

            # Import here to avoid circular imports
            from .jwt_service import jwt_service

            # Create access token
            access_token = jwt_service.create_access_token(user, session)
            expires_in = settings.jwt_access_token_expire_minutes * 60

            # Log token creation
            self._log_audit_event(
                db,
                user.id,
                "refresh_token_created",
                f"Refresh token oluşturuldu: {session.id}",
                {
                    "session_id": str(session.id),
                    "token_length": len(refresh_token),
                    "expires_in_days": self.refresh_token_expire_days,
                },
            )

            elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            logger.info(
                "Refresh token session created",
                extra={
                    "operation": "create_refresh_session",
                    "user_id": user.id,
                    "session_id": str(session.id),
                    "expires_in_days": self.refresh_token_expire_days,
                    "elapsed_ms": elapsed_ms,
                },
            )

            return RefreshTokenResult(
                session=session,
                refresh_token=refresh_token,
                access_token=access_token,
                expires_in=expires_in,
            )

        except SessionSecurityError as e:
            raise TokenServiceError(e.code, e.message, e.details)
        except Exception as e:
            logger.error(
                "Refresh session creation failed",
                exc_info=True,
                extra={
                    "operation": "create_refresh_session",
                    "user_id": user.id,
                    "error_type": type(e).__name__,
                },
            )
            raise TokenServiceError(
                "ERR-REFRESH-CREATION-FAILED", "Refresh token oluşturma başarısız"
            )

    def rotate_refresh_token(
        self,
        db: DBSession,
        current_refresh_token: str,
        device_fingerprint: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> RefreshTokenResult:
        """
        Rotate refresh token with reuse detection and security analysis.

        Args:
            db: Database session
            current_refresh_token: Current refresh token to rotate
            device_fingerprint: Device fingerprint for verification
            ip_address: Client IP address
            user_agent: Client user agent

        Returns:
            RefreshTokenResult with new session and tokens

        Raises:
            TokenServiceError: If rotation fails or reuse detected
        """
        start_time = datetime.now(timezone.utc)

        try:
            # Hash the current token for lookup
            token_hash = self.hash_refresh_token(current_refresh_token)

            # Find current session
            current_session = (
                db.query(Session)
                .filter(Session.refresh_token_hash == token_hash, Session.revoked_at.is_(None))
                .first()
            )

            if not current_session:
                # Check if token was recently revoked (reuse detection)
                revoked_session = (
                    db.query(Session)
                    .filter(
                        Session.refresh_token_hash == token_hash,
                        Session.revoked_at.isnot(None),
                        Session.revoked_at
                        > datetime.now(timezone.utc)
                        - timedelta(hours=self.reuse_detection_window_hours),
                    )
                    .first()
                )

                if revoked_session:
                    # SECURITY ALERT: Refresh token reuse detected
                    self._handle_refresh_token_reuse(db, revoked_session, ip_address, user_agent)

                raise TokenServiceError(
                    "ERR-REFRESH-REUSE",
                    "Refresh token yeniden kullanım girişimi tespit edildi. Güvenlik nedeniyle tüm oturumlar sonlandırıldı.",
                )

            # Verify session is still valid
            if not current_session.is_active:
                raise TokenServiceError(
                    "ERR-REFRESH-INVALID", "Refresh token geçersiz veya süresi dolmuş"
                )

            # Check rotation chain length for security
            chain_length = current_session.get_rotation_chain_length()
            if chain_length >= self.max_rotation_chain:
                logger.warning(
                    "Excessive rotation chain detected",
                    extra={
                        "user_id": current_session.user_id,
                        "session_id": str(current_session.id),
                        "chain_length": chain_length,
                    },
                )

                # Force new session instead of rotation
                current_session.revoke("excessive_rotation_chain")
                user = current_session.user
                return self.create_refresh_session(
                    db, user, device_fingerprint, ip_address, user_agent
                )

            # Analyze device fingerprint for anomalies
            if device_fingerprint and current_session.device_fingerprint:
                if device_fingerprint != current_session.device_fingerprint:
                    self._log_security_event(
                        db,
                        current_session.user_id,
                        "DEVICE_FINGERPRINT_MISMATCH",
                        ip_address,
                        user_agent,
                        {
                            "session_id": str(current_session.id),
                            "old_fingerprint": current_session.device_fingerprint[:50] + "...",
                            "new_fingerprint": device_fingerprint[:50] + "...",
                        },
                    )

            # Use session service for secure rotation
            new_session, new_refresh_token = self.session_service.rotate_session(
                db=db,
                current_refresh_token=current_refresh_token,
                device_fingerprint=device_fingerprint,
                ip_address=ip_address,
                user_agent=user_agent,
            )

            # Import here to avoid circular imports
            from .jwt_service import jwt_service

            # Create new access token
            access_token = jwt_service.create_access_token(new_session.user, new_session)
            expires_in = settings.jwt_access_token_expire_minutes * 60

            # Log successful rotation
            self._log_audit_event(
                db,
                new_session.user_id,
                "refresh_token_rotated",
                f"Refresh token rotasyonu tamamlandı: {current_session.id} → {new_session.id}",
                {
                    "old_session_id": str(current_session.id),
                    "new_session_id": str(new_session.id),
                    "chain_length": chain_length + 1,
                },
            )

            elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)

            logger.info(
                "Refresh token rotated successfully",
                extra={
                    "operation": "rotate_refresh_token",
                    "user_id": new_session.user_id,
                    "old_session_id": str(current_session.id),
                    "new_session_id": str(new_session.id),
                    "chain_length": chain_length + 1,
                    "elapsed_ms": elapsed_ms,
                },
            )

            return RefreshTokenResult(
                session=new_session,
                refresh_token=new_refresh_token,
                access_token=access_token,
                expires_in=expires_in,
            )

        except TokenServiceError:
            raise  # Re-raise our custom errors
        except Exception as e:
            logger.error(
                "Refresh token rotation failed",
                exc_info=True,
                extra={"operation": "rotate_refresh_token", "error_type": type(e).__name__},
            )
            raise TokenServiceError(
                "ERR-REFRESH-ROTATION-FAILED", "Refresh token rotasyonu başarısız"
            )

    def revoke_refresh_token(
        self, db: DBSession, refresh_token: str, reason: str = "user_logout"
    ) -> bool:
        """
        Revoke specific refresh token.

        Args:
            db: Database session
            refresh_token: Token to revoke
            reason: Revocation reason

        Returns:
            True if token was revoked, False if not found
        """
        try:
            session_id = self.session_service.revoke_session_by_token(db, refresh_token, reason)

            if session_id:
                logger.info(
                    "Refresh token revoked",
                    extra={
                        "operation": "revoke_refresh_token",
                        "session_id": str(session_id),
                        "reason": reason,
                    },
                )
                return True

            return False

        except Exception as e:
            logger.error(
                "Refresh token revocation failed",
                exc_info=True,
                extra={
                    "operation": "revoke_refresh_token",
                    "reason": reason,
                    "error_type": type(e).__name__,
                },
            )
            raise TokenServiceError(
                "ERR-REFRESH-REVOCATION-FAILED", "Refresh token iptali başarısız"
            )

    def revoke_all_refresh_tokens(
        self, db: DBSession, user_id: int, reason: str = "logout_all"
    ) -> int:
        """
        Revoke all refresh tokens for a user.

        Args:
            db: Database session
            user_id: User ID
            reason: Revocation reason

        Returns:
            Number of tokens revoked
        """
        try:
            revoked_count = self.session_service.revoke_all_user_sessions(db, user_id, reason)

            self._log_audit_event(
                db,
                user_id,
                "all_refresh_tokens_revoked",
                f"Tüm refresh token'lar iptal edildi: {revoked_count} oturum",
                {"revoked_count": revoked_count, "reason": reason},
            )

            logger.info(
                "All refresh tokens revoked for user",
                extra={
                    "operation": "revoke_all_refresh_tokens",
                    "user_id": user_id,
                    "revoked_count": revoked_count,
                    "reason": reason,
                },
            )

            return revoked_count

        except Exception as e:
            logger.error(
                "All refresh tokens revocation failed",
                exc_info=True,
                extra={
                    "operation": "revoke_all_refresh_tokens",
                    "user_id": user_id,
                    "error_type": type(e).__name__,
                },
            )
            raise TokenServiceError(
                "ERR-REFRESH-REVOCATION-ALL-FAILED", "Tüm refresh token iptali başarısız"
            )

    def set_refresh_cookie(self, response: Response, refresh_token: str) -> None:
        """
        Set secure refresh token cookie with enterprise security attributes.

        Args:
            response: FastAPI response object
            refresh_token: Refresh token to set in cookie
        """
        cookie_kwargs = {
            "key": self.cookie_name,
            "value": refresh_token,
            "max_age": self.cookie_max_age,
            "httponly": True,
            "secure": self.cookie_secure,
            "samesite": self.cookie_samesite,
            "path": "/",
        }

        # Add domain if configured
        if self.cookie_domain:
            cookie_kwargs["domain"] = self.cookie_domain

        response.set_cookie(**cookie_kwargs)

        logger.debug(
            "Refresh token cookie set",
            extra={
                "operation": "set_refresh_cookie",
                "cookie_name": self.cookie_name,
                "max_age": self.cookie_max_age,
                "secure": self.cookie_secure,
                "samesite": self.cookie_samesite,
            },
        )

    def clear_refresh_cookie(self, response: Response) -> None:
        """
        Clear refresh token cookie.

        Args:
            response: FastAPI response object
        """
        response.delete_cookie(
            key=self.cookie_name,
            path="/",
            domain=self.cookie_domain,
            secure=self.cookie_secure,
            samesite=self.cookie_samesite,
        )

        logger.debug(
            "Refresh token cookie cleared",
            extra={"operation": "clear_refresh_cookie", "cookie_name": self.cookie_name},
        )

    def get_refresh_token_from_request(self, request: Request) -> Optional[str]:
        """
        Extract refresh token from request cookie.

        Args:
            request: FastAPI request object

        Returns:
            Refresh token or None if not found
        """
        return request.cookies.get(self.cookie_name)

    def _handle_refresh_token_reuse(
        self,
        db: DBSession,
        compromised_session: Session,
        ip_address: Optional[str],
        user_agent: Optional[str],
    ) -> None:
        """
        Handle refresh token reuse attack with immediate security response.

        Args:
            db: Database session
            compromised_session: The compromised session
            ip_address: Attacker IP address
            user_agent: Attacker user agent
        """
        user_id = compromised_session.user_id

        # IMMEDIATE SECURITY RESPONSE:
        # 1. Revoke ALL sessions for the user (nuclear option)
        revoked_count = self.session_service.revoke_all_user_sessions(
            db, user_id, "refresh_token_reuse_detected"
        )

        # 2. Log critical security event
        self._log_security_event(
            db,
            user_id,
            "REFRESH_TOKEN_REUSE_ATTACK",
            ip_address,
            user_agent,
            {
                "compromised_session_id": str(compromised_session.id),
                "sessions_revoked": revoked_count,
                "attack_timestamp": datetime.now(timezone.utc).isoformat(),
                "severity": "CRITICAL",
            },
        )

        # 3. Log audit event
        self._log_audit_event(
            db,
            user_id,
            "security_breach_refresh_reuse",
            f"Refresh token yeniden kullanım saldırısı tespit edildi. {revoked_count} oturum iptal edildi.",
            {
                "compromised_session_id": str(compromised_session.id),
                "sessions_revoked": revoked_count,
                "response_action": "all_sessions_revoked",
            },
        )

        logger.critical(
            "SECURITY ALERT: Refresh token reuse attack detected",
            extra={
                "operation": "handle_refresh_token_reuse",
                "user_id": user_id,
                "compromised_session_id": str(compromised_session.id),
                "sessions_revoked": revoked_count,
                "attacker_ip": ip_address,
                "attacker_user_agent": user_agent,
                "severity": "CRITICAL",
            },
        )

    def _log_security_event(
        self,
        db: DBSession,
        user_id: int,
        event_type: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
        details: Dict[str, Any],
    ) -> None:
        """Log security event."""
        try:
            security_event = SecurityEvent(
                user_id=user_id,
                event_type=event_type,
                ip_address=ip_address,
                user_agent=user_agent,
                details=details,
                severity="HIGH" if "REUSE" in event_type else "MEDIUM",
            )
            db.add(security_event)
            db.flush()
        except Exception as e:
            logger.error(
                "Failed to log security event",
                exc_info=True,
                extra={"event_type": event_type, "user_id": user_id},
            )

    def _log_audit_event(
        self, db: DBSession, user_id: int, action: str, description: str, details: Dict[str, Any]
    ) -> None:
        """Log audit event."""
        try:
            audit_log = AuditLog(
                user_id=user_id, action=action, description=description, details=details
            )
            db.add(audit_log)
            db.flush()
        except Exception as e:
            logger.error(
                "Failed to log audit event",
                exc_info=True,
                extra={"action": action, "user_id": user_id},
            )


# Global token service instance
token_service = TokenService()
