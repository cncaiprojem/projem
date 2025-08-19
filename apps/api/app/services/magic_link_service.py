"""
Ultra Enterprise Magic Link Service for Task 3.6

This service implements banking-level passwordless authentication with:
- itsdangerous cryptographic token signing with HMAC
- Single-use enforcement with database-backed tracking
- 15-minute expiration with cryptographic validation
- Email enumeration protection (always returns 202)
- Rate limiting and security audit logging
- Integration with existing session and JWT services
"""

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session as DBSession

from ..config import settings
from ..core.logging import get_logger
from ..models.audit_log import AuditLog
from ..models.magic_link import MagicLink
from ..models.security_event import SecurityEvent
from ..models.user import User
from .session_service import SessionService
from .token_service import token_service

logger = get_logger(__name__)


class MagicLinkError(Exception):
    """Base magic link service error with Turkish localization."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class SignatureExpired(Exception):
    """Token signature expired error."""
    pass


class BadSignature(Exception):
    """Invalid token signature error."""
    pass


class MagicLinkResult:
    """Result of magic link consumption."""

    def __init__(
        self,
        user: User,
        access_token: str,
        refresh_token: str,
        expires_in: int,
        session_id: str
    ):
        self.user = user
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in = expires_in
        self.session_id = session_id


class MagicLinkService:
    """Ultra enterprise magic link authentication service."""

    def __init__(self):
        self.session_service = SessionService()

        # Magic link configuration
        self.token_expiry_minutes = 15
        self.max_attempts_per_hour = 5
        self.cleanup_interval_hours = 24

        # Cryptographic configuration
        self.secret_key = getattr(settings, 'MAGIC_LINK_SECRET', settings.secret_key)
        self.algorithm = 'HS256'  # HMAC-SHA256

        # Email configuration (placeholder - integrate with actual email service)
        self.base_url = getattr(settings, 'BASE_URL', 'http://localhost:3000')

    def _create_token(self, payload: dict[str, Any]) -> str:
        """Create cryptographically signed token using HMAC."""
        # Add expiration
        payload['exp'] = int((datetime.now(UTC) + timedelta(minutes=self.token_expiry_minutes)).timestamp())

        # Encode payload
        message = json.dumps(payload, sort_keys=True)
        message_b64 = base64.urlsafe_b64encode(message.encode('utf-8')).decode('utf-8').rstrip('=')

        # Create HMAC signature
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            message_b64.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # Combine into token
        token = f"{message_b64}.{signature}"
        return token

    def _verify_token(self, token: str) -> dict[str, Any]:
        """Verify token signature and decode payload."""
        try:
            # Split token
            if '.' not in token:
                raise BadSignature("Invalid token format")

            message_b64, signature = token.rsplit('.', 1)

            # Verify signature
            expected_signature = hmac.new(
                self.secret_key.encode('utf-8'),
                message_b64.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_signature):
                raise BadSignature("Invalid token signature")

            # Decode payload
            # Add padding if needed
            padding = 4 - (len(message_b64) % 4)
            if padding != 4:
                message_b64 += '=' * padding

            message = base64.urlsafe_b64decode(message_b64).decode('utf-8')
            payload = json.loads(message)

            # Check expiration
            if 'exp' in payload:
                exp_timestamp = payload['exp']
                if datetime.now(UTC).timestamp() > exp_timestamp:
                    raise SignatureExpired("Token has expired")

            return payload

        except json.JSONDecodeError:
            raise BadSignature("Invalid token payload")
        except (ValueError, KeyError):
            raise BadSignature("Malformed token")

    def request_magic_link(
        self,
        db: DBSession,
        email: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_fingerprint: str | None = None
    ) -> bool:
        """
        Request magic link for email (always returns success for security).
        
        Args:
            db: Database session
            email: Target email address
            ip_address: Client IP address
            user_agent: Client user agent
            device_fingerprint: Device fingerprint
            
        Returns:
            Always True for email enumeration protection
            
        Raises:
            MagicLinkError: If rate limiting is exceeded
        """
        start_time = datetime.now(UTC)
        email = email.lower().strip()

        try:
            # Rate limiting check
            if not self._check_rate_limit(db, email, ip_address):
                self._log_security_event(
                    db, None, 'MAGIC_LINK_RATE_LIMITED',
                    ip_address, user_agent, {
                        'email_hash': hash(email) % 1000000,
                        'reason': 'rate_limit_exceeded'
                    }
                )
                raise MagicLinkError(
                    'ERR-ML-RATE-LIMITED',
                    'Çok fazla magic link talebi. Lütfen 1 saat sonra tekrar deneyin.'
                )

            # Check if user exists (but don't reveal this information)
            user = db.query(User).filter(User.email == email).first()

            if user:
                # Generate and store magic link for existing user
                magic_link_token = self._create_magic_link(
                    db, email, ip_address, user_agent, device_fingerprint
                )

                # Send email (this would integrate with actual email service)
                self._send_magic_link_email(email, magic_link_token)

                # Log successful request
                self._log_audit_event(
                    db, user.id, 'magic_link_requested',
                    f'Magic link istendi: {email}',
                    {
                        'email_hash': hash(email) % 1000000,
                        'token_length': len(magic_link_token)
                    }
                )

                logger.info("Magic link requested for existing user", extra={
                    'operation': 'request_magic_link',
                    'user_id': user.id,
                    'email_hash': hash(email) % 1000000,
                    'ip_address': ip_address
                })
            else:
                # Log attempt for non-existent user (security monitoring)
                self._log_security_event(
                    db, None, 'MAGIC_LINK_NONEXISTENT_USER',
                    ip_address, user_agent, {
                        'email_hash': hash(email) % 1000000,
                        'reason': 'user_not_found'
                    }
                )

                logger.warning("Magic link requested for non-existent user", extra={
                    'operation': 'request_magic_link',
                    'email_hash': hash(email) % 1000000,
                    'ip_address': ip_address
                })

            elapsed_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            # Always return True for email enumeration protection
            return True

        except MagicLinkError:
            raise  # Re-raise our custom errors
        except Exception as e:
            logger.error("Magic link request failed", exc_info=True, extra={
                'operation': 'request_magic_link',
                'email_hash': hash(email) % 1000000,
                'error_type': type(e).__name__
            })
            # Still return True for security
            return True

    def consume_magic_link(
        self,
        db: DBSession,
        token: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
        device_fingerprint: str | None = None
    ) -> MagicLinkResult:
        """
        Consume magic link token and create authenticated session.
        
        Args:
            db: Database session
            token: Magic link token to consume
            ip_address: Client IP address
            user_agent: Client user agent
            device_fingerprint: Device fingerprint
            
        Returns:
            MagicLinkResult with user and tokens
            
        Raises:
            MagicLinkError: If consumption fails
        """
        start_time = datetime.now(UTC)

        try:
            # Parse and validate token
            payload = self._validate_token(token)
            email = payload['email']
            nonce = payload['nonce']

            # Find magic link record
            magic_link = db.query(MagicLink).filter(
                MagicLink.nonce == nonce,
                MagicLink.email == email
            ).first()

            if not magic_link:
                raise MagicLinkError(
                    'ERR-ML-INVALID',
                    'Magic link geçersiz veya bulunamadı'
                )

            # Increment attempt counter
            magic_link.increment_attempt()

            # Validate magic link state
            if magic_link.is_consumed:
                self._log_security_event(
                    db, None, 'MAGIC_LINK_REUSE_ATTEMPT',
                    ip_address, user_agent, {
                        'magic_link_id': str(magic_link.id),
                        'email_hash': hash(email) % 1000000,
                        'original_consumed_at': magic_link.consumed_at.isoformat()
                    }
                )
                raise MagicLinkError(
                    'ERR-ML-ALREADY-USED',
                    'Magic link zaten kullanılmış'
                )

            if magic_link.is_expired:
                magic_link.invalidate('expired')
                raise MagicLinkError(
                    'ERR-ML-EXPIRED',
                    'Magic link süresi dolmuş'
                )

            if not magic_link.is_valid:
                raise MagicLinkError(
                    'ERR-ML-INVALID',
                    'Magic link geçersiz'
                )

            # Find user
            user = db.query(User).filter(User.email == email).first()
            if not user:
                raise MagicLinkError(
                    'ERR-ML-USER-NOT-FOUND',
                    'Kullanıcı bulunamadı'
                )

            # Check user account status
            if not user.can_attempt_login():
                raise MagicLinkError(
                    'ERR-ML-ACCOUNT-LOCKED',
                    'Hesap kilitli veya aktif değil'
                )

            # Consume magic link
            magic_link.consume(ip_address, user_agent, device_fingerprint)

            # Create authenticated session
            token_result = token_service.create_refresh_session(
                db=db,
                user=user,
                device_fingerprint=device_fingerprint,
                ip_address=ip_address,
                user_agent=user_agent
            )

            # Update user login metadata
            user.reset_failed_login_attempts()
            user.update_login_metadata(ip_address or '', user_agent or '')

            # Log successful consumption
            self._log_audit_event(
                db, user.id, 'magic_link_consumed',
                f'Magic link başarıyla kullanıldı: {email}',
                {
                    'magic_link_id': str(magic_link.id),
                    'session_id': str(token_result.session.id),
                    'device_fingerprint_match': (
                        device_fingerprint == magic_link.device_fingerprint
                        if device_fingerprint and magic_link.device_fingerprint
                        else None
                    )
                }
            )

            # Commit all changes
            db.commit()

            elapsed_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)

            logger.info("Magic link consumed successfully", extra={
                'operation': 'consume_magic_link',
                'user_id': user.id,
                'session_id': str(token_result.session.id),
                'magic_link_id': str(magic_link.id),
                'elapsed_ms': elapsed_ms
            })

            return MagicLinkResult(
                user=user,
                access_token=token_result.access_token,
                refresh_token=token_result.refresh_token,
                expires_in=token_result.expires_in,
                session_id=str(token_result.session.id)
            )

        except MagicLinkError:
            db.rollback()
            raise  # Re-raise our custom errors
        except SignatureExpired:
            db.rollback()
            raise MagicLinkError(
                'ERR-ML-EXPIRED',
                'Magic link süresi dolmuş'
            )
        except BadSignature:
            db.rollback()
            raise MagicLinkError(
                'ERR-ML-INVALID',
                'Magic link geçersiz'
            )
        except Exception as e:
            db.rollback()
            logger.error("Magic link consumption failed", exc_info=True, extra={
                'operation': 'consume_magic_link',
                'error_type': type(e).__name__
            })
            raise MagicLinkError(
                'ERR-ML-CONSUMPTION-FAILED',
                'Magic link kullanımı başarısız'
            )

    def cleanup_expired_links(self, db: DBSession) -> int:
        """
        Clean up expired magic links.
        
        Args:
            db: Database session
            
        Returns:
            Number of cleaned up links
        """
        try:
            cutoff_time = datetime.now(UTC) - timedelta(hours=self.cleanup_interval_hours)

            # Find expired links
            expired_links = db.query(MagicLink).filter(
                or_(
                    and_(
                        MagicLink.consumed_at.is_(None),
                        MagicLink.invalidated_at.is_(None),
                        MagicLink.issued_at < cutoff_time
                    ),
                    MagicLink.invalidated_at.isnot(None),
                    MagicLink.consumed_at.isnot(None)
                )
            ).all()

            cleanup_count = len(expired_links)

            # Mark as expired
            for link in expired_links:
                if not link.invalidated_at:
                    link.invalidate('expired')

            db.commit()

            logger.info("Magic links cleanup completed", extra={
                'operation': 'cleanup_expired_links',
                'cleanup_count': cleanup_count
            })

            return cleanup_count

        except Exception as e:
            db.rollback()
            logger.error("Magic links cleanup failed", exc_info=True, extra={
                'operation': 'cleanup_expired_links',
                'error_type': type(e).__name__
            })
            return 0

    def _create_magic_link(
        self,
        db: DBSession,
        email: str,
        ip_address: str | None,
        user_agent: str | None,
        device_fingerprint: str | None
    ) -> str:
        """Create magic link token and database record."""
        # Generate secure nonce
        nonce = secrets.token_urlsafe(32)

        # Create database record
        magic_link = MagicLink(
            email=email,
            nonce=nonce,
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=device_fingerprint
        )

        db.add(magic_link)
        db.flush()  # Get ID

        # Create signed token
        payload = {
            'email': email,
            'nonce': nonce,
            'iat': int(datetime.now(UTC).timestamp())
        }

        token = self._create_token(payload)

        return token

    def _validate_token(self, token: str) -> dict[str, Any]:
        """Validate and decode magic link token."""
        try:
            payload = self._verify_token(token)

            # Validate required fields
            if not all(key in payload for key in ['email', 'nonce', 'iat']):
                raise MagicLinkError(
                    'ERR-ML-MALFORMED',
                    'Magic link formatı geçersiz'
                )

            return payload

        except SignatureExpired:
            raise MagicLinkError(
                'ERR-ML-EXPIRED',
                'Magic link süresi dolmuş'
            )
        except BadSignature:
            raise MagicLinkError(
                'ERR-ML-INVALID',
                'Magic link geçersiz'
            )

    def _check_rate_limit(
        self,
        db: DBSession,
        email: str,
        ip_address: str | None
    ) -> bool:
        """Check rate limiting for magic link requests."""
        cutoff_time = datetime.now(UTC) - timedelta(hours=1)

        # Check email-based rate limit
        email_count = db.query(func.count(MagicLink.id)).filter(
            MagicLink.email == email,
            MagicLink.issued_at > cutoff_time
        ).scalar()

        if email_count >= self.max_attempts_per_hour:
            return False

        # Check IP-based rate limit (if IP available)
        if ip_address:
            ip_count = db.query(func.count(MagicLink.id)).filter(
                MagicLink.ip_address == ip_address,
                MagicLink.issued_at > cutoff_time
            ).scalar()

            if ip_count >= self.max_attempts_per_hour * 2:  # More lenient for IP
                return False

        return True

    def _send_magic_link_email(self, email: str, token: str) -> None:
        """Send magic link email (placeholder for email service integration)."""
        magic_link_url = f"{self.base_url}/auth/magic-link/consume?token={token}"

        # TODO: Integrate with actual email service
        logger.info("Magic link email would be sent", extra={
            'operation': 'send_magic_link_email',
            'email_hash': hash(email) % 1000000,
            'url_length': len(magic_link_url)
        })

        # Placeholder email content:
        # Subject: Giriş Bağlantınız - FreeCAD CNC/CAM
        # Body: Aşağıdaki bağlantıya tıklayarak hesabınıza giriş yapabilirsiniz:
        #       {magic_link_url}
        #       Bu bağlantı 15 dakika içinde geçerliliğini yitirecektir.

    def _log_security_event(
        self,
        db: DBSession,
        user_id: int | None,
        event_type: str,
        ip_address: str | None,
        user_agent: str | None,
        details: dict[str, Any]
    ) -> None:
        """Log security event."""
        try:
            security_event = SecurityEvent(
                user_id=user_id,
                event_type=event_type,
                ip_address=ip_address,
                user_agent=user_agent,
                details=details,
                severity='HIGH' if 'REUSE' in event_type or 'RATE_LIMITED' in event_type else 'MEDIUM'
            )
            db.add(security_event)
            db.flush()
        except Exception:
            logger.error("Failed to log security event", exc_info=True, extra={
                'event_type': event_type,
                'user_id': user_id
            })

    def _log_audit_event(
        self,
        db: DBSession,
        user_id: int | None,
        action: str,
        description: str,
        details: dict[str, Any]
    ) -> None:
        """Log audit event."""
        try:
            audit_log = AuditLog(
                user_id=user_id,
                action=action,
                description=description,
                details=details
            )
            db.add(audit_log)
            db.flush()
        except Exception:
            logger.error("Failed to log audit event", exc_info=True, extra={
                'action': action,
                'user_id': user_id
            })


# Global magic link service instance
magic_link_service = MagicLinkService()
