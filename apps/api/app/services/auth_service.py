"""
Ultra Enterprise Authentication Service for Task 3.1

This service implements banking-level authentication with:
- Secure user registration and login
- Account lockout protection
- Audit logging with PII masking
- Turkish KVKV compliance
- Password reset functionality
- Device fingerprinting support
"""

import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple, Any
import ipaddress

from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from ..models.user import User
from ..models.security_event import SecurityEvent
from ..core.logging import get_logger
from ..settings import app_settings as settings
from .password_service import password_service

logger = get_logger(__name__)


class AuthenticationError(Exception):
    """Base exception for authentication errors."""
    
    def __init__(self, code: str, message: str, details: Optional[Dict] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class AuthService:
    """Ultra enterprise authentication service."""
    
    def __init__(self):
        self.max_failed_attempts = 10
        self.lockout_duration_minutes = 15
        self.password_reset_token_lifetime_hours = 1
        self.email_verification_token_lifetime_hours = 24
    
    def register_user(
        self, 
        db: Session, 
        email: str, 
        password: str, 
        full_name: Optional[str] = None,
        data_processing_consent: bool = True,
        marketing_consent: bool = False,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> User:
        """
        Register new user with enterprise security validation.
        
        Args:
            db: Database session
            email: User email address
            password: Plain text password
            full_name: Optional full name
            data_processing_consent: KVKV data processing consent
            marketing_consent: Marketing communication consent
            ip_address: Client IP address for audit
            user_agent: Client user agent for audit
            
        Returns:
            Created User instance
            
        Raises:
            AuthenticationError: If registration fails
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Validate email uniqueness
            existing_user = db.query(User).filter(User.email == email.lower()).first()
            if existing_user:
                self._log_security_event(
                    db, None, 'REGISTRATION_DUPLICATE_EMAIL', 
                    ip_address, user_agent, {'email': self._mask_email(email)}
                )
                raise AuthenticationError(
                    'ERR-AUTH-EMAIL-TAKEN',
                    'Bu e-posta adresi zaten kullanılmaktadır'
                )
            
            # Validate password strength
            strength_result = password_service.validate_password_strength(
                password, 
                {'email': email, 'full_name': full_name}
            )
            
            if not strength_result.ok:
                self._log_security_event(
                    db, None, 'REGISTRATION_WEAK_PASSWORD',
                    ip_address, user_agent, {
                        'email': self._mask_email(email),
                        'password_score': strength_result.score,
                        'feedback_count': len(strength_result.feedback)
                    }
                )
                raise AuthenticationError(
                    'ERR-AUTH-WEAK-PASSWORD',
                    'Şifre güvenlik gereksinimlerini karşılamıyor: ' + ', '.join(strength_result.feedback)
                )
            
            # Hash password with enterprise security
            password_hash, salt, algorithm = password_service.hash_password(password)
            
            # Create user with enterprise fields
            user = User(
                email=email.lower(),
                full_name=full_name,
                display_name=full_name,
                password_hash=password_hash,
                password_salt=salt,
                password_algorithm=algorithm,
                password_updated_at=datetime.now(timezone.utc),
                account_status='active',
                data_processing_consent=data_processing_consent,
                data_processing_consent_at=datetime.now(timezone.utc) if data_processing_consent else None,
                marketing_consent=marketing_consent,
                marketing_consent_at=datetime.now(timezone.utc) if marketing_consent else None,
                email_verification_token=password_service.generate_secure_token(),
                email_verification_expires_at=datetime.now(timezone.utc) + timedelta(hours=self.email_verification_token_lifetime_hours),
                auth_metadata={
                    'registration_ip': ip_address,
                    'registration_user_agent': user_agent,
                    'registration_timestamp': datetime.now(timezone.utc).isoformat(),
                    'kvkv_consent_version': '1.0',
                }
            )
            
            # Save user
            db.add(user)
            db.flush()  # Get user ID
            
            # Log successful registration
            self._log_security_event(
                db, user.id, 'USER_REGISTERED', 
                ip_address, user_agent, {
                    'email': self._mask_email(email),
                    'has_full_name': bool(full_name),
                    'data_processing_consent': data_processing_consent,
                    'marketing_consent': marketing_consent,
                }
            )
            
            elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            logger.info("User registered successfully", extra={
                'operation': 'user_registration',
                'user_id': user.id,
                'email': self._mask_email(email),
                'elapsed_ms': elapsed_ms,
                'has_full_name': bool(full_name),
                'kvkv_consent': data_processing_consent,
            })
            
            db.commit()
            return user
            
        except AuthenticationError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error("User registration failed", exc_info=True, extra={
                'operation': 'user_registration',
                'email': self._mask_email(email),
                'error_type': type(e).__name__,
            })
            raise AuthenticationError(
                'ERR-AUTH-REGISTRATION-FAILED',
                'Kayıt işlemi başarısız oldu, lütfen tekrar deneyin'
            )
    
    def authenticate_user(
        self,
        db: Session,
        email: str,
        password: str,
        device_fingerprint: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[User, Dict[str, Any]]:
        """
        Authenticate user with enterprise security.
        
        Args:
            db: Database session
            email: User email
            password: Plain text password
            device_fingerprint: Optional device fingerprint
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            Tuple of (User, auth_metadata)
            
        Raises:
            AuthenticationError: If authentication fails
        """
        start_time = datetime.now(timezone.utc)
        
        try:
            # Find user by email
            user = db.query(User).filter(User.email == email.lower()).first()
            
            if not user:
                # Perform timing-safe dummy operation
                password_service.verify_password("dummy", "dummy", "dummy")
                
                self._log_security_event(
                    db, None, 'LOGIN_USER_NOT_FOUND',
                    ip_address, user_agent, {'email': self._mask_email(email)}
                )
                
                raise AuthenticationError(
                    'ERR-AUTH-INVALID-CREDS',
                    'E-posta adresi veya şifre hatalı'
                )
            
            # Check if account can attempt login
            if not user.can_attempt_login():
                if user.is_account_locked():
                    self._log_security_event(
                        db, user.id, 'LOGIN_ACCOUNT_LOCKED',
                        ip_address, user_agent, {
                            'email': self._mask_email(email),
                            'locked_until': user.account_locked_until.isoformat() if user.account_locked_until else None,
                            'failed_attempts': user.failed_login_attempts,
                        }
                    )
                    
                    raise AuthenticationError(
                        'ERR-AUTH-LOCKED',
                        f'Hesap geçici olarak kilitlendi. Lütfen {self.lockout_duration_minutes} dakika sonra tekrar deneyin.'
                    )
                else:
                    self._log_security_event(
                        db, user.id, 'LOGIN_ACCOUNT_INACTIVE',
                        ip_address, user_agent, {
                            'email': self._mask_email(email),
                            'account_status': user.account_status,
                            'is_active': user.is_active,
                        }
                    )
                    
                    raise AuthenticationError(
                        'ERR-AUTH-ACCOUNT-INACTIVE',
                        'Hesap aktif değil, lütfen yönetici ile iletişime geçin'
                    )
            
            # Verify password
            password_valid = password_service.verify_password(
                password, 
                user.password_hash, 
                user.password_salt, 
                user.password_algorithm
            )
            
            if not password_valid:
                # Increment failed attempts
                user.increment_failed_login_attempts()
                
                self._log_security_event(
                    db, user.id, 'LOGIN_INVALID_PASSWORD',
                    ip_address, user_agent, {
                        'email': self._mask_email(email),
                        'failed_attempts': user.failed_login_attempts,
                        'account_locked': user.is_account_locked(),
                    }
                )
                
                db.commit()  # Save failed attempt immediately
                
                if user.is_account_locked():
                    raise AuthenticationError(
                        'ERR-AUTH-LOCKED',
                        f'Çok fazla başarısız deneme. Hesap {self.lockout_duration_minutes} dakika kilitlendi.'
                    )
                else:
                    remaining_attempts = self.max_failed_attempts - user.failed_login_attempts
                    raise AuthenticationError(
                        'ERR-AUTH-INVALID-CREDS',
                        f'E-posta adresi veya şifre hatalı. Kalan deneme hakkı: {remaining_attempts}'
                    )
            
            # Check if password must be changed
            if user.password_must_change or user.is_password_expired():
                self._log_security_event(
                    db, user.id, 'LOGIN_PASSWORD_EXPIRED',
                    ip_address, user_agent, {
                        'email': self._mask_email(email),
                        'password_must_change': user.password_must_change,
                        'password_expired': user.is_password_expired(),
                    }
                )
                
                raise AuthenticationError(
                    'ERR-AUTH-PASSWORD-EXPIRED',
                    'Şifre süresi dolmuş, lütfen yeni şifre belirleyin'
                )
            
            # Successful authentication
            user.reset_failed_login_attempts()
            user.update_login_metadata(ip_address or '', user_agent or '')
            
            # Update auth metadata
            auth_metadata = {
                'login_timestamp': datetime.now(timezone.utc).isoformat(),
                'device_fingerprint': device_fingerprint,
                'ip_address': ip_address,
                'user_agent': user_agent,
                'auth_method': 'password',
            }
            
            self._log_security_event(
                db, user.id, 'LOGIN_SUCCESS',
                ip_address, user_agent, {
                    'email': self._mask_email(email),
                    'total_login_count': user.total_login_count,
                    'device_fingerprint': device_fingerprint,
                }
            )
            
            elapsed_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            logger.info("User authenticated successfully", extra={
                'operation': 'user_authentication',
                'user_id': user.id,
                'email': self._mask_email(email),
                'elapsed_ms': elapsed_ms,
                'total_logins': user.total_login_count,
            })
            
            db.commit()
            return user, auth_metadata
            
        except AuthenticationError:
            raise
        except Exception as e:
            logger.error("User authentication failed", exc_info=True, extra={
                'operation': 'user_authentication',
                'email': self._mask_email(email),
                'error_type': type(e).__name__,
            })
            raise AuthenticationError(
                'ERR-AUTH-SYSTEM-ERROR',
                'Sistem hatası, lütfen tekrar deneyin'
            )
    
    def initiate_password_reset(
        self,
        db: Session,
        email: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """
        Initiate password reset process.
        
        Args:
            db: Database session
            email: User email address
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            Always True (for security, don't reveal if email exists)
        """
        try:
            user = db.query(User).filter(User.email == email.lower()).first()
            
            if user and user.can_reset_password():
                # Generate secure reset token
                reset_token = password_service.generate_secure_token(48)
                
                # Set reset token and expiration
                user.password_reset_token = reset_token
                user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(
                    hours=self.password_reset_token_lifetime_hours
                )
                user.password_reset_attempts += 1
                
                self._log_security_event(
                    db, user.id, 'PASSWORD_RESET_INITIATED',
                    ip_address, user_agent, {
                        'email': self._mask_email(email),
                        'reset_attempts': user.password_reset_attempts,
                    }
                )
                
                # TODO: Send password reset email
                # email_service.send_password_reset_email(user.email, reset_token)
                
                db.commit()
                
                logger.info("Password reset initiated", extra={
                    'operation': 'password_reset_initiate',
                    'user_id': user.id,
                    'email': self._mask_email(email),
                })
            else:
                # Log attempt even if user doesn't exist (for security monitoring)
                self._log_security_event(
                    db, None, 'PASSWORD_RESET_UNKNOWN_EMAIL',
                    ip_address, user_agent, {'email': self._mask_email(email)}
                )
            
            # Always return True for security (don't reveal if email exists)
            return True
            
        except Exception as e:
            logger.error("Password reset initiation failed", exc_info=True, extra={
                'operation': 'password_reset_initiate',
                'email': self._mask_email(email),
                'error_type': type(e).__name__,
            })
            return True  # Still return True for security
    
    def reset_password(
        self,
        db: Session,
        token: str,
        new_password: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> User:
        """
        Complete password reset with new password.
        
        Args:
            db: Database session
            token: Password reset token
            new_password: New password
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            User instance
            
        Raises:
            AuthenticationError: If reset fails
        """
        try:
            # Find user by reset token
            user = db.query(User).filter(
                User.password_reset_token == token,
                User.password_reset_expires_at > datetime.now(timezone.utc)
            ).first()
            
            if not user:
                self._log_security_event(
                    db, None, 'PASSWORD_RESET_INVALID_TOKEN',
                    ip_address, user_agent, {'token_prefix': token[:8] if token else None}
                )
                
                raise AuthenticationError(
                    'ERR-AUTH-INVALID-TOKEN',
                    'Geçersiz veya süresi dolmuş şifre sıfırlama bağlantısı'
                )
            
            # Validate new password strength
            strength_result = password_service.validate_password_strength(
                new_password,
                {
                    'email': user.email,
                    'full_name': user.full_name,
                    'company_name': user.company_name
                }
            )
            
            if not strength_result.ok:
                self._log_security_event(
                    db, user.id, 'PASSWORD_RESET_WEAK_PASSWORD',
                    ip_address, user_agent, {
                        'email': self._mask_email(user.email),
                        'password_score': strength_result.score,
                    }
                )
                
                raise AuthenticationError(
                    'ERR-AUTH-WEAK-PASSWORD',
                    'Yeni şifre güvenlik gereksinimlerini karşılamıyor: ' + ', '.join(strength_result.feedback)
                )
            
            # Hash new password
            password_hash, salt, algorithm = password_service.hash_password(new_password)
            
            # Update user password
            user.password_hash = password_hash
            user.password_salt = salt
            user.password_algorithm = algorithm
            user.password_updated_at = datetime.now(timezone.utc)
            user.password_must_change = False
            
            # Clear reset token
            user.password_reset_token = None
            user.password_reset_expires_at = None
            user.password_reset_attempts = 0
            
            # Reset failed login attempts
            user.failed_login_attempts = 0
            user.account_locked_until = None
            
            self._log_security_event(
                db, user.id, 'PASSWORD_RESET_COMPLETED',
                ip_address, user_agent, {
                    'email': self._mask_email(user.email),
                }
            )
            
            logger.info("Password reset completed", extra={
                'operation': 'password_reset_complete',
                'user_id': user.id,
                'email': self._mask_email(user.email),
            })
            
            db.commit()
            return user
            
        except AuthenticationError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error("Password reset failed", exc_info=True, extra={
                'operation': 'password_reset_complete',
                'error_type': type(e).__name__,
            })
            raise AuthenticationError(
                'ERR-AUTH-RESET-FAILED',
                'Şifre sıfırlama işlemi başarısız, lütfen tekrar deneyin'
            )
    
    def _log_security_event(
        self,
        db: Session,
        user_id: Optional[int],
        event_type: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
        details: Optional[Dict] = None
    ) -> None:
        """Log security event for audit purposes."""
        try:
            event = SecurityEvent(
                user_id=user_id,
                type=event_type,
                ip=self._mask_ip_if_needed(ip_address),
                ua=user_agent,
                created_at=datetime.now(timezone.utc)
            )
            db.add(event)
            db.flush()
            
            # Log details separately for audit trail (with PII masking)
            if details:
                logger.info("Security event details", extra={
                    'event_id': event.id,
                    'event_type': event_type,
                    'user_id': user_id,
                    'details': details,
                })
        except Exception as e:
            logger.error("Failed to log security event", exc_info=True, extra={
                'event_type': event_type,
                'user_id': user_id,
                'error_type': type(e).__name__,
            })
    
    def _mask_email(self, email: str) -> str:
        """Mask email for logging (KVKV compliance)."""
        if not email or '@' not in email:
            return 'invalid_email'
        
        local, domain = email.split('@', 1)
        if len(local) <= 2:
            masked_local = '*' * len(local)
        else:
            masked_local = local[0] + '*' * (len(local) - 2) + local[-1]
        
        return f"{masked_local}@{domain}"
    
    def _mask_ip_if_needed(self, ip_address: Optional[str]) -> Optional[str]:
        """Mask IP address for privacy compliance if needed."""
        if not ip_address:
            return None
        
        try:
            ip = ipaddress.ip_address(ip_address)
            if ip.is_private:
                return ip_address  # Private IPs are not PII
            
            # Mask public IP addresses for privacy
            if isinstance(ip, ipaddress.IPv4Address):
                # Mask last octet: 192.168.1.xxx
                parts = ip_address.split('.')
                return f"{'.'.join(parts[:3])}.xxx"
            else:
                # Mask IPv6 suffix
                return f"{ip_address[:19]}::xxxx"
        except ValueError:
            return 'invalid_ip'


# Global instance
auth_service = AuthService()