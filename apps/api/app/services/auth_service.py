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
from ..models.enums import UserRole
from ..core.logging import get_logger
from ..middleware.correlation_middleware import get_correlation_id, get_session_id
from ..services.audit_service import audit_service
from ..services.security_event_service import (
    SecurityEventType, 
    SecuritySeverity, 
    security_event_service
)
from ..services.pii_masking_service import (
    DataClassification,
    pii_masking_service
)
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
    
    async def register_user(
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
                await await self._log_security_event(
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
                await await self._log_security_event(
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
            await self._log_security_event(
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
    
    async def authenticate_user(
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
                
                await self._log_security_event(
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
                    await self._log_security_event(
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
                    await self._log_security_event(
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
                
                await self._log_security_event(
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
                await self._log_security_event(
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
            
            await self._log_security_event(
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
    
    async def initiate_password_reset(
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
                
                await self._log_security_event(
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
                await self._log_security_event(
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
    
    async def reset_password(
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
                await self._log_security_event(
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
                await self._log_security_event(
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
            
            await self._log_security_event(
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
    
    async def create_oidc_user(
        self,
        db: Session,
        email: str,
        full_name: Optional[str] = None,
        picture: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> User:
        """
        Create a new user account for OIDC authentication.
        
        Args:
            db: Database session
            email: User email address (verified by OIDC provider)
            full_name: User's full name from OIDC provider
            picture: Profile picture URL from OIDC provider
            ip_address: Client IP address
            user_agent: Client user agent
            
        Returns:
            User instance
            
        Raises:
            AuthenticationError: If user creation fails
        """
        try:
            # Check if user already exists
            existing_user = db.query(User).filter(User.email == email.lower()).first()
            if existing_user:
                raise AuthenticationError(
                    'ERR-OIDC-EMAIL-CONFLICT',
                    'Email adresi başka bir hesapla ilişkili'
                )
            
            # Create new user for OIDC authentication
            user = User(
                email=email.lower(),
                full_name=full_name,
                display_name=full_name,
                # No password fields for OIDC-only users
                password_hash=None,
                password_salt=None,
                password_algorithm='none',  # Indicates OIDC-only account
                password_updated_at=None,
                password_must_change=False,
                # Account is active and email is verified (verified by OIDC provider)
                account_status='active',
                email_verified_at=datetime.now(timezone.utc),
                is_email_verified=True,
                is_verified=True,
                is_active=True,
                # Default role for new users
                role=UserRole.ENGINEER,  # Default role for OIDC users
                # KVKV compliance (implied consent through OIDC login)
                data_processing_consent=True,
                data_processing_consent_at=datetime.now(timezone.utc),
                marketing_consent=False,  # Default to False, user can opt-in later
                # Login metadata
                last_login_ip=ip_address,
                last_login_user_agent=user_agent,
                last_successful_login_at=datetime.now(timezone.utc),
                total_login_count=1,
                # Initialize security fields
                failed_login_attempts=0,
                account_locked_until=None,
                # Set auth metadata
                auth_metadata={
                    'auth_method': 'oidc',
                    'oidc_provider': 'google',
                    'picture_url': picture,
                    'created_via_oidc': True,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                    'ip_address': ip_address,
                    'user_agent': user_agent
                }
            )
            
            db.add(user)
            db.flush()  # Get user ID
            
            # Log user creation
            await self._log_security_event(
                db, user.id, 'OIDC_USER_CREATED',
                ip_address, user_agent, {
                    'email': self._mask_email(email),
                    'full_name': full_name,
                    'auth_method': 'oidc',
                    'provider': 'google'
                }
            )
            
            logger.info("OIDC user created successfully", extra={
                'operation': 'create_oidc_user',
                'user_id': user.id,
                'email': self._mask_email(email),
                'provider': 'google',
                'has_full_name': bool(full_name),
                'has_picture': bool(picture)
            })
            
            return user
            
        except AuthenticationError:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error("OIDC user creation failed", exc_info=True, extra={
                'operation': 'create_oidc_user',
                'email': self._mask_email(email),
                'error_type': type(e).__name__
            })
            raise AuthenticationError(
                'ERR-OIDC-USER-CREATION-FAILED',
                'OIDC kullanıcı hesabı oluşturulamadı'
            )
    
    async def _log_security_event(
        self,
        db: Session,
        user_id: Optional[int],
        event_type: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
        details: Optional[Dict] = None
    ) -> None:
        """Log security event using ultra-enterprise security service."""
        try:
            # Map legacy event types to new SecurityEventType enum
            event_type_mapping = {
                'USER_REGISTERED': SecurityEventType.LOGIN_SUCCESS,
                'LOGIN_SUCCESS': SecurityEventType.LOGIN_SUCCESS,
                'LOGIN_FAILED': SecurityEventType.LOGIN_FAILED,
                'ACCOUNT_LOCKED': SecurityEventType.LOGIN_BLOCKED,
                'PASSWORD_RESET_REQUESTED': SecurityEventType.ACCESS_GRANTED,
                'PASSWORD_RESET_COMPLETED': SecurityEventType.ACCESS_GRANTED,
                'EMAIL_VERIFICATION_SENT': SecurityEventType.ACCESS_GRANTED,
                'EMAIL_VERIFIED': SecurityEventType.ACCESS_GRANTED,
                'REGISTRATION_DUPLICATE_EMAIL': SecurityEventType.ACCESS_DENIED,
                'REGISTRATION_WEAK_PASSWORD': SecurityEventType.ACCESS_DENIED,
                'INVALID_RESET_TOKEN': SecurityEventType.ACCESS_DENIED,
                'PASSWORD_VALIDATION_FAILED': SecurityEventType.ACCESS_DENIED,
                'SUSPICIOUS_LOGIN': SecurityEventType.SUSPICIOUS_LOGIN
            }
            
            # Determine severity based on event type
            severity_mapping = {
                SecurityEventType.LOGIN_SUCCESS: SecuritySeverity.INFO,
                SecurityEventType.LOGIN_FAILED: SecuritySeverity.MEDIUM,
                SecurityEventType.LOGIN_BLOCKED: SecuritySeverity.HIGH,
                SecurityEventType.ACCESS_DENIED: SecuritySeverity.MEDIUM,
                SecurityEventType.SUSPICIOUS_LOGIN: SecuritySeverity.HIGH
            }
            
            mapped_event_type = event_type_mapping.get(event_type, SecurityEventType.ACCESS_DENIED)
            severity = severity_mapping.get(mapped_event_type, SecuritySeverity.MEDIUM)
            
            # Create comprehensive security event
            await security_event_service.create_security_event(
                db=db,
                event_type=mapped_event_type,
                severity=severity,
                user_id=user_id,
                resource="authentication_system",
                ip_address=ip_address,
                user_agent=user_agent,
                metadata={
                    "legacy_event_type": event_type,
                    "event_details": details or {},
                    "service": "auth_service",
                    "compliance": "KVKV_GDPR"
                }
            )
            
            # Also create audit entry for authentication events
            await audit_service.create_audit_entry(
                db=db,
                event_type=f"auth_{event_type.lower()}",
                user_id=user_id,
                scope_type="authentication",
                scope_id=user_id,
                resource="auth_system",
                ip_address=ip_address,
                user_agent=user_agent,
                payload={
                    "event_type": event_type,
                    "event_details": details or {},
                    "security_level": severity.value,
                    "compliance_framework": "KVKV_GDPR"
                },
                classification=DataClassification.PERSONAL
            )
            
        except Exception as e:
            logger.error("Failed to log security event", exc_info=True, extra={
                'event_type': event_type,
                'user_id': user_id,
                'error_type': type(e).__name__,
                'correlation_id': get_correlation_id()
            })
    
    def _mask_email(self, email: str) -> str:
        """Mask email for logging using ultra-enterprise PII masking service."""
        return pii_masking_service.mask_email(email)
    
    def _mask_ip_if_needed(self, ip_address: Optional[str]) -> Optional[str]:
        """Mask IP address using ultra-enterprise PII masking service."""
        if not ip_address:
            return None
        return pii_masking_service.mask_ip_address(ip_address)


# Global instance
auth_service = AuthService()