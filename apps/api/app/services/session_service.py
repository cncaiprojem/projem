"""
Ultra Enterprise Session Service for Task 3.2

This service implements banking-level session management with:
- Secure session creation and rotation
- Device fingerprint anomaly detection
- Session revocation and cleanup
- Audit logging with Turkish KVKV compliance
- Refresh token reuse detection
- Session security monitoring
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session as DBSession

from ..core.logging import get_logger
from ..models.audit_log import AuditLog
from ..models.security_event import SecurityEvent
from ..models.session import Session
from ..models.user import User
from ..settings import app_settings as settings

logger = get_logger(__name__)


class SessionSecurityError(Exception):
    """Base exception for session security errors."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class SessionService:
    """Ultra enterprise session management service with banking-level security."""

    def __init__(self):
        self.default_session_lifetime_hours = 168  # 7 days
        self.max_sessions_per_user = 10
        self.refresh_token_length = 64  # 512 bits
        self.max_rotation_chain_length = 50
        self.suspicious_activity_threshold = 5

        # Session secret for HMAC (from settings in production)
        self.session_secret = getattr(settings, 'SESSION_SECRET', 'dev-session-secret-key')

    def create_session(
        self,
        db: DBSession,
        user_id: int,
        device_fingerprint: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        expires_in_hours: int | None = None
    ) -> tuple[Session, str]:
        """
        Create new session with enterprise security.
        
        Args:
            db: Database session
            user_id: User ID
            device_fingerprint: Device fingerprint for anomaly detection
            ip_address: Client IP address
            user_agent: Client user agent
            expires_in_hours: Custom expiration (default 7 days)
            
        Returns:
            Tuple of (Session, plaintext_refresh_token)
            
        Raises:
            SessionSecurityError: If session creation fails
        """
        start_time = datetime.now(UTC)

        try:
            # Verify user exists and is active
            user = db.query(User).filter(User.id == user_id).first()
            if not user:
                raise SessionSecurityError(
                    'ERR-SESSION-USER-NOT-FOUND',
                    'Kullanıcı bulunamadı'
                )

            if not user.can_attempt_login():
                raise SessionSecurityError(
                    'ERR-SESSION-USER-INACTIVE',
                    'Kullanıcı hesabı aktif değil'
                )

            # Check for too many active sessions
            active_sessions = self._get_active_sessions(db, user_id)
            if len(active_sessions) >= self.max_sessions_per_user:
                # Revoke oldest session
                oldest_session = min(active_sessions, key=lambda s: s.created_at)
                self.revoke_session(
                    db, oldest_session.id, 'max_sessions_exceeded',
                    ip_address, user_agent
                )

                self._log_security_event(
                    db, user_id, 'SESSION_LIMIT_EXCEEDED',
                    ip_address, user_agent, {
                        'active_sessions': len(active_sessions),
                        'max_allowed': self.max_sessions_per_user,
                        'revoked_session_id': str(oldest_session.id)
                    }
                )

            # Check for suspicious device fingerprint activity
            if device_fingerprint:
                suspicious = self._analyze_device_fingerprint(
                    db, user_id, device_fingerprint, ip_address
                )
                if suspicious:
                    self._log_security_event(
                        db, user_id, 'SUSPICIOUS_DEVICE_DETECTED',
                        ip_address, user_agent, {
                            'device_fingerprint': device_fingerprint[:50] + '...',
                            'analysis_result': suspicious
                        }
                    )

            # Generate secure refresh token
            refresh_token = secrets.token_urlsafe(self.refresh_token_length)
            refresh_token_hash = self._hash_refresh_token(refresh_token)

            # Create session
            expires_hours = expires_in_hours or self.default_session_lifetime_hours
            session = Session.create_default_session(
                user_id=user_id,
                refresh_token_hash=refresh_token_hash,
                device_fingerprint=device_fingerprint,
                ip_address=self._mask_ip_for_storage(ip_address),
                user_agent=user_agent,
                expires_in_hours=expires_hours
            )

            # Check if session should be flagged as suspicious
            if device_fingerprint and suspicious:
                session.flag_suspicious()

            # Save session
            db.add(session)
            db.flush()  # Get session ID

            # Log session creation
            self._log_security_event(
                db, user_id, 'SESSION_CREATED',
                ip_address, user_agent, {
                    'session_id': str(session.id),
                    'expires_at': session.expires_at.isoformat(),
                    'device_fingerprint': bool(device_fingerprint),
                    'is_suspicious': session.is_suspicious,
                }
            )

            # Create audit log entry
            self._create_audit_log(
                db, user_id, 'session_created',
                f'Yeni oturum oluşturuldu: {session.id}',
                {'session_id': str(session.id), 'expires_hours': expires_hours}
            )

            elapsed_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            logger.info("Session created successfully", extra={
                'operation': 'session_create',
                'user_id': user_id,
                'session_id': str(session.id),
                'elapsed_ms': elapsed_ms,
                'expires_in_hours': expires_hours,
                'has_device_fingerprint': bool(device_fingerprint),
            })

            db.commit()
            return session, refresh_token

        except SessionSecurityError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error("Session creation failed", exc_info=True, extra={
                'operation': 'session_create',
                'user_id': user_id,
                'error_type': type(e).__name__,
            })
            raise SessionSecurityError(
                'ERR-SESSION-CREATION-FAILED',
                'Oturum oluşturma başarısız, lütfen tekrar deneyin'
            )

    def rotate_session(
        self,
        db: DBSession,
        current_refresh_token: str,
        device_fingerprint: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> tuple[Session, str]:
        """
        Rotate session with refresh token reuse detection.
        
        Args:
            db: Database session
            current_refresh_token: Current refresh token
            device_fingerprint: Device fingerprint
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            Tuple of (new_session, new_refresh_token)
            
        Raises:
            SessionSecurityError: If rotation fails
        """
        start_time = datetime.now(UTC)

        try:
            # Hash the provided refresh token
            refresh_token_hash = self._hash_refresh_token(current_refresh_token)

            # Find current session
            current_session = db.query(Session).filter(
                Session.refresh_token_hash == refresh_token_hash,
                Session.revoked_at.is_(None)
            ).first()

            if not current_session or not current_session.is_active:
                # Check if token was already used (refresh token reuse)
                revoked_session = db.query(Session).filter(
                    Session.refresh_token_hash == refresh_token_hash,
                    Session.revoked_at.is_not(None)
                ).first()

                if revoked_session:
                    # SECURITY ALERT: Refresh token reuse detected
                    self._handle_refresh_token_reuse(
                        db, revoked_session.user_id,
                        ip_address, user_agent, revoked_session.id
                    )

                raise SessionSecurityError(
                    'ERR-SESSION-INVALID-TOKEN',
                    'Geçersiz veya süresi dolmuş oturum'
                )

            # Verify session hasn't expired
            if current_session.is_expired:
                current_session.revoke('expired')
                db.commit()

                raise SessionSecurityError(
                    'ERR-SESSION-EXPIRED',
                    'Oturum süresi dolmuş, lütfen tekrar giriş yapın'
                )

            # Check rotation chain length for security
            chain_length = current_session.get_rotation_chain_length()
            if chain_length >= self.max_rotation_chain_length:
                self._log_security_event(
                    db, current_session.user_id, 'SESSION_ROTATION_LIMIT',
                    ip_address, user_agent, {
                        'chain_length': chain_length,
                        'max_allowed': self.max_rotation_chain_length,
                        'session_id': str(current_session.id)
                    }
                )

                # Force re-authentication
                self.revoke_session(
                    db, current_session.id, 'rotation_limit_exceeded',
                    ip_address, user_agent
                )

                raise SessionSecurityError(
                    'ERR-SESSION-ROTATION-LIMIT',
                    'Güvenlik nedeniyle tekrar giriş yapmanız gerekiyor'
                )

            # Verify device consistency if fingerprint provided
            if (device_fingerprint and current_session.device_fingerprint and
                device_fingerprint != current_session.device_fingerprint):

                self._log_security_event(
                    db, current_session.user_id, 'SESSION_DEVICE_MISMATCH',
                    ip_address, user_agent, {
                        'session_id': str(current_session.id),
                        'original_fingerprint': current_session.device_fingerprint[:50] + '...',
                        'new_fingerprint': device_fingerprint[:50] + '...'
                    }
                )

                # Flag as suspicious but allow rotation
                current_session.flag_suspicious()

            # Generate new refresh token
            new_refresh_token = secrets.token_urlsafe(self.refresh_token_length)
            new_refresh_token_hash = self._hash_refresh_token(new_refresh_token)

            # Create new session with rotation chain
            new_session = Session.create_default_session(
                user_id=current_session.user_id,
                refresh_token_hash=new_refresh_token_hash,
                device_fingerprint=device_fingerprint or current_session.device_fingerprint,
                ip_address=self._mask_ip_for_storage(ip_address),
                user_agent=user_agent,
                expires_in_hours=self.default_session_lifetime_hours
            )
            new_session.rotated_from = current_session.id

            # Revoke current session
            current_session.revoke('rotation')

            # Save new session
            db.add(new_session)
            db.flush()

            # Log session rotation
            self._log_security_event(
                db, current_session.user_id, 'SESSION_ROTATED',
                ip_address, user_agent, {
                    'old_session_id': str(current_session.id),
                    'new_session_id': str(new_session.id),
                    'chain_length': chain_length + 1,
                    'device_consistent': device_fingerprint == current_session.device_fingerprint
                }
            )

            self._create_audit_log(
                db, current_session.user_id, 'session_rotated',
                f'Oturum döndürüldü: {current_session.id} -> {new_session.id}',
                {
                    'old_session_id': str(current_session.id),
                    'new_session_id': str(new_session.id)
                }
            )

            elapsed_ms = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            logger.info("Session rotated successfully", extra={
                'operation': 'session_rotate',
                'user_id': current_session.user_id,
                'old_session_id': str(current_session.id),
                'new_session_id': str(new_session.id),
                'elapsed_ms': elapsed_ms,
                'chain_length': chain_length + 1,
            })

            db.commit()
            return new_session, new_refresh_token

        except SessionSecurityError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error("Session rotation failed", exc_info=True, extra={
                'operation': 'session_rotate',
                'error_type': type(e).__name__,
            })
            raise SessionSecurityError(
                'ERR-SESSION-ROTATION-FAILED',
                'Oturum yenileme başarısız, lütfen tekrar giriş yapın'
            )

    def revoke_session(
        self,
        db: DBSession,
        session_id: uuid.UUID,
        reason: str = 'user_request',
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> bool:
        """
        Revoke session with audit logging.
        
        Args:
            db: Database session
            session_id: Session ID to revoke
            reason: Revocation reason
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            True if session was revoked
        """
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if not session:
                return False

            if session.revoked_at:
                return True  # Already revoked

            # Revoke session
            session.revoke(reason)

            # Log revocation
            self._log_security_event(
                db, session.user_id, 'SESSION_REVOKED',
                ip_address, user_agent, {
                    'session_id': str(session.id),
                    'reason': reason,
                    'session_age_hours': round(session.age_in_seconds / 3600, 2)
                }
            )

            self._create_audit_log(
                db, session.user_id, 'session_revoked',
                f'Oturum iptal edildi: {session.id} (sebep: {reason})',
                {'session_id': str(session.id), 'reason': reason}
            )

            logger.info("Session revoked", extra={
                'operation': 'session_revoke',
                'user_id': session.user_id,
                'session_id': str(session.id),
                'reason': reason,
            })

            db.commit()
            return True

        except Exception as e:
            db.rollback()
            logger.error("Session revocation failed", exc_info=True, extra={
                'operation': 'session_revoke',
                'session_id': str(session_id),
                'error_type': type(e).__name__,
            })
            return False

    def revoke_all_user_sessions(
        self,
        db: DBSession,
        user_id: int,
        reason: str = 'security_action',
        except_session_id: uuid.UUID | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None
    ) -> int:
        """
        Revoke all sessions for a user (except optionally one).
        
        Args:
            db: Database session
            user_id: User ID
            reason: Revocation reason
            except_session_id: Session ID to preserve
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            Number of sessions revoked
        """
        try:
            query = db.query(Session).filter(
                Session.user_id == user_id,
                Session.revoked_at.is_(None)
            )

            if except_session_id:
                query = query.filter(Session.id != except_session_id)

            sessions = query.all()
            revoked_count = 0

            for session in sessions:
                session.revoke(reason)
                revoked_count += 1

            if revoked_count > 0:
                self._log_security_event(
                    db, user_id, 'ALL_SESSIONS_REVOKED',
                    ip_address, user_agent, {
                        'revoked_count': revoked_count,
                        'reason': reason,
                        'preserved_session_id': str(except_session_id) if except_session_id else None
                    }
                )

                self._create_audit_log(
                    db, user_id, 'all_sessions_revoked',
                    f'Tüm oturumlar iptal edildi ({revoked_count} oturum)',
                    {'revoked_count': revoked_count, 'reason': reason}
                )

            db.commit()
            return revoked_count

        except Exception as e:
            db.rollback()
            logger.error("Bulk session revocation failed", exc_info=True, extra={
                'operation': 'revoke_all_sessions',
                'user_id': user_id,
                'error_type': type(e).__name__,
            })
            return 0

    def cleanup_expired_sessions(self, db: DBSession) -> int:
        """
        Clean up expired sessions for security and performance.
        
        Args:
            db: Database session
            
        Returns:
            Number of sessions cleaned up
        """
        try:
            # Find expired sessions that aren't already revoked
            expired_sessions = db.query(Session).filter(
                Session.expires_at < datetime.now(UTC),
                Session.revoked_at.is_(None)
            ).all()

            cleanup_count = 0
            for session in expired_sessions:
                session.revoke('expired')
                cleanup_count += 1

            if cleanup_count > 0:
                logger.info("Expired sessions cleaned up", extra={
                    'operation': 'session_cleanup',
                    'cleaned_count': cleanup_count,
                })

            db.commit()
            return cleanup_count

        except Exception as e:
            db.rollback()
            logger.error("Session cleanup failed", exc_info=True, extra={
                'operation': 'session_cleanup',
                'error_type': type(e).__name__,
            })
            return 0

    def get_session_by_token(
        self,
        db: DBSession,
        refresh_token: str
    ) -> Session | None:
        """
        Get session by refresh token with security validation.
        
        Args:
            db: Database session
            refresh_token: Refresh token
            
        Returns:
            Session if valid, None otherwise
        """
        try:
            refresh_token_hash = self._hash_refresh_token(refresh_token)

            session = db.query(Session).filter(
                Session.refresh_token_hash == refresh_token_hash,
                Session.revoked_at.is_(None)
            ).first()

            if session and session.is_active:
                # Update last used timestamp
                session.update_last_used()
                db.commit()
                return session

            return None

        except Exception as e:
            logger.error("Session lookup failed", exc_info=True, extra={
                'operation': 'session_lookup',
                'error_type': type(e).__name__,
            })
            return None

    def _get_active_sessions(self, db: DBSession, user_id: int) -> list[Session]:
        """Get all active sessions for a user."""
        return db.query(Session).filter(
            Session.user_id == user_id,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC)
        ).all()

    def _hash_refresh_token(self, token: str) -> str:
        """Hash refresh token with HMAC-SHA512."""
        return hmac.new(
            self.session_secret.encode(),
            token.encode(),
            hashlib.sha512
        ).hexdigest()

    def _mask_ip_for_storage(self, ip_address: str | None) -> str | None:
        """Mask IP address for KVKV compliance storage."""
        if not ip_address:
            return None

        # Use same masking logic as auth_service for consistency
        try:
            import ipaddress
            ip = ipaddress.ip_address(ip_address)
            if ip.is_private:
                return ip_address  # Private IPs are not PII

            # Mask public IP addresses for privacy
            if isinstance(ip, ipaddress.IPv4Address):
                parts = ip_address.split('.')
                return f"{'.'.join(parts[:3])}.xxx"
            else:
                return f"{ip_address[:19]}::xxxx"
        except ValueError:
            return 'invalid_ip'

    def _analyze_device_fingerprint(
        self,
        db: DBSession,
        user_id: int,
        device_fingerprint: str,
        ip_address: str | None
    ) -> dict[str, Any] | None:
        """Analyze device fingerprint for suspicious activity."""
        try:
            # Check if this fingerprint was used by other users (account sharing)
            other_users = db.query(Session.user_id).filter(
                Session.device_fingerprint == device_fingerprint,
                Session.user_id != user_id,
                Session.created_at > datetime.now(UTC) - timedelta(days=30)
            ).distinct().count()

            if other_users > 0:
                return {
                    'type': 'device_sharing',
                    'other_users_count': other_users,
                    'risk_level': 'medium'
                }

            # Check for rapid device changes for this user
            recent_fingerprints = db.query(Session.device_fingerprint).filter(
                Session.user_id == user_id,
                Session.device_fingerprint.is_not(None),
                Session.device_fingerprint != device_fingerprint,
                Session.created_at > datetime.now(UTC) - timedelta(hours=24)
            ).distinct().count()

            if recent_fingerprints >= self.suspicious_activity_threshold:
                return {
                    'type': 'rapid_device_changes',
                    'recent_fingerprints': recent_fingerprints,
                    'risk_level': 'high'
                }

            return None

        except Exception as e:
            logger.error("Device fingerprint analysis failed", exc_info=True, extra={
                'operation': 'device_analysis',
                'user_id': user_id,
                'error_type': type(e).__name__,
            })
            return None

    def _handle_refresh_token_reuse(
        self,
        db: DBSession,
        user_id: int,
        ip_address: str | None,
        user_agent: str | None,
        compromised_session_id: uuid.UUID
    ) -> None:
        """Handle refresh token reuse detection - SECURITY CRITICAL."""
        # This is a critical security event - token reuse indicates:
        # 1. Token theft/interception
        # 2. Client-side storage compromise
        # 3. Man-in-the-middle attack

        # Immediately revoke ALL user sessions
        revoked_count = self.revoke_all_user_sessions(
            db, user_id, 'token_reuse_detected',
            ip_address=ip_address, user_agent=user_agent
        )

        # Log critical security event
        self._log_security_event(
            db, user_id, 'REFRESH_TOKEN_REUSE_DETECTED',
            ip_address, user_agent, {
                'compromised_session_id': str(compromised_session_id),
                'revoked_sessions_count': revoked_count,
                'action': 'all_sessions_revoked',
                'severity': 'critical'
            }
        )

        # Create high-priority audit log
        self._create_audit_log(
            db, user_id, 'security_breach',
            'GÜVENLIK UYARISI: Refresh token yeniden kullanımı tespit edildi. Tüm oturumlar iptal edildi.',
            {
                'compromised_session_id': str(compromised_session_id),
                'revoked_sessions': revoked_count,
                'security_level': 'critical'
            }
        )

        # TODO: In production, add additional security measures:
        # - Send security alert email to user
        # - Notify security team
        # - Consider temporary account suspension
        # - Rate limit future authentication attempts

        logger.critical("SECURITY ALERT: Refresh token reuse detected", extra={
            'operation': 'token_reuse_detected',
            'user_id': user_id,
            'compromised_session_id': str(compromised_session_id),
            'revoked_sessions': revoked_count,
            'ip_address': ip_address,
        })

    def _log_security_event(
        self,
        db: DBSession,
        user_id: int | None,
        event_type: str,
        ip_address: str | None,
        user_agent: str | None,
        details: dict | None = None
    ) -> None:
        """Log security event for audit purposes."""
        try:
            event = SecurityEvent(
                user_id=user_id,
                type=event_type,
                ip=self._mask_ip_for_storage(ip_address),
                ua=user_agent,
                created_at=datetime.now(UTC)
            )
            db.add(event)
            db.flush()

            if details:
                logger.info("Session security event", extra={
                    'event_id': event.id,
                    'event_type': event_type,
                    'user_id': user_id,
                    'details': details,
                })
        except Exception as e:
            logger.error("Failed to log session security event", exc_info=True, extra={
                'event_type': event_type,
                'user_id': user_id,
                'error_type': type(e).__name__,
            })

    def _create_audit_log(
        self,
        db: DBSession,
        user_id: int,
        action: str,
        description: str,
        metadata: dict | None = None
    ) -> None:
        """Create audit log entry for session operations."""
        try:
            audit_log = AuditLog(
                actor_user_id=user_id,
                entity_type='session',
                entity_id=str(user_id),  # Use user_id as entity_id for sessions
                action=action,
                description=description,
                metadata=metadata or {},
                created_at=datetime.now(UTC)
            )
            db.add(audit_log)
            db.flush()
        except Exception as e:
            logger.error("Failed to create session audit log", exc_info=True, extra={
                'action': action,
                'user_id': user_id,
                'error_type': type(e).__name__,
            })


# Global instance
session_service = SessionService()
