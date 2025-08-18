"""
Ultra-Enterprise MFA TOTP Service for Task 3.7

Implements banking-level security TOTP (Time-based One-Time Password) with:
- pyotp library for RFC 6238 compliance (period=30, digits=6)
- AES-256-GCM encryption for secret storage
- Secure QR code generation with base64 encoding
- Backup codes with SHA-256 hashing
- Turkish KVKV compliance for personal data protection
- Comprehensive audit logging
- Rate limiting and timing attack protection
"""

import base64
import hashlib
import hmac
import secrets
import time
import io
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Tuple, Dict, Any

import pyotp
import qrcode
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from sqlalchemy.orm import Session

from ..models.user import User
from ..models.mfa_backup_code import MFABackupCode
from ..models.audit_log import AuditLog
from ..models.security_event import SecurityEvent
from ..core.logging import get_logger
from ..settings import app_settings as settings

logger = get_logger(__name__)


class MFAError(Exception):
    """MFA operation error with error codes."""
    
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


class TOTPService:
    """TOTP service for ultra-enterprise MFA security."""
    
    TOTP_PERIOD = 30  # 30 second window
    TOTP_DIGITS = 6   # 6 digit codes
    TOTP_ALGORITHM = "SHA1"  # Standard TOTP algorithm
    SECRET_LENGTH = 32  # 32 byte secret (160 bits)
    
    # Rate limiting
    MAX_VERIFY_ATTEMPTS = 5  # Max verification attempts per window
    VERIFY_WINDOW = 300  # 5 minute window
    
    # Backup codes
    BACKUP_CODE_COUNT = 10  # 10 backup codes
    BACKUP_CODE_LENGTH = 8   # 8 character codes
    
    def __init__(self):
        self.encryption_key = self._get_encryption_key()
        self._verify_attempts: Dict[int, List[float]] = {}
    
    def _get_encryption_key(self) -> bytes:
        """Derive encryption key from settings."""
        # Use PBKDF2 to derive key from SECRET_KEY
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 256 bits
            salt=b'mfa_secret_salt_v1',  # Static salt for key derivation
            iterations=100000,
        )
        return kdf.derive(settings.SECRET_KEY.encode())
    
    def _encrypt_secret(self, secret: str) -> str:
        """Encrypt TOTP secret using AES-256-GCM."""
        try:
            aesgcm = AESGCM(self.encryption_key)
            nonce = secrets.token_bytes(12)  # 96-bit nonce
            ciphertext = aesgcm.encrypt(nonce, secret.encode(), None)
            # Combine nonce + ciphertext and encode as base64
            encrypted_data = nonce + ciphertext
            return base64.b64encode(encrypted_data).decode()
        except Exception as e:
            logger.error("Failed to encrypt MFA secret", exc_info=True)
            raise MFAError(
                'ERR-MFA-ENCRYPTION-FAILED',
                'MFA şifresi şifrelenirken hata oluştu',
                {'error': str(e)}
            )
    
    def _decrypt_secret(self, encrypted_secret: str) -> str:
        """Decrypt TOTP secret using AES-256-GCM."""
        try:
            encrypted_data = base64.b64decode(encrypted_secret.encode())
            nonce = encrypted_data[:12]  # First 12 bytes are nonce
            ciphertext = encrypted_data[12:]  # Rest is ciphertext
            
            aesgcm = AESGCM(self.encryption_key)
            decrypted = aesgcm.decrypt(nonce, ciphertext, None)
            return decrypted.decode()
        except Exception as e:
            logger.error("Failed to decrypt MFA secret", exc_info=True)
            raise MFAError(
                'ERR-MFA-DECRYPTION-FAILED',
                'MFA şifresi çözülürken hata oluştu',
                {'error': str(e)}
            )
    
    def _generate_secret(self) -> str:
        """Generate cryptographically secure TOTP secret."""
        return pyotp.random_base32(length=self.SECRET_LENGTH)
    
    def _check_rate_limit(self, user_id: int) -> bool:
        """Check if user has exceeded verification rate limits."""
        now = time.time()
        if user_id not in self._verify_attempts:
            self._verify_attempts[user_id] = []
        
        # Remove old attempts outside the window
        self._verify_attempts[user_id] = [
            timestamp for timestamp in self._verify_attempts[user_id]
            if now - timestamp < self.VERIFY_WINDOW
        ]
        
        # Check if under limit
        return len(self._verify_attempts[user_id]) < self.MAX_VERIFY_ATTEMPTS
    
    def _record_verify_attempt(self, user_id: int) -> None:
        """Record verification attempt for rate limiting."""
        now = time.time()
        if user_id not in self._verify_attempts:
            self._verify_attempts[user_id] = []
        self._verify_attempts[user_id].append(now)
    
    def _generate_backup_codes(self) -> List[str]:
        """Generate cryptographically secure backup codes."""
        codes = []
        for _ in range(self.BACKUP_CODE_COUNT):
            # Generate 8 character alphanumeric codes
            code = ''.join(secrets.choice('23456789ABCDEFGHJKLMNPQRSTUVWXYZ') 
                          for _ in range(self.BACKUP_CODE_LENGTH))
            codes.append(code)
        return codes
    
    def _hash_backup_code(self, code: str) -> str:
        """Hash backup code using SHA-256."""
        return hashlib.sha256(code.encode()).hexdigest()
    
    def _create_backup_code_hint(self, code: str) -> str:
        """Create hint from backup code (first 4 + last 4 chars)."""
        if len(code) >= 8:
            return code[:4] + code[-4:]
        return code[:4].ljust(8, '*')
    
    def _constant_time_compare(self, a: str, b: str) -> bool:
        """Constant time string comparison to prevent timing attacks."""
        return hmac.compare_digest(a.encode(), b.encode())
    
    def setup_mfa(self, db: Session, user: User, 
                  ip_address: Optional[str] = None,
                  user_agent: Optional[str] = None) -> Dict[str, Any]:
        """
        Setup MFA for user - generate secret and return setup data.
        Does not enable MFA until verification is complete.
        """
        if user.mfa_enabled:
            raise MFAError(
                'ERR-MFA-ALREADY-ENABLED',
                'MFA zaten aktif'
            )
        
        # Generate new secret
        secret = self._generate_secret()
        encrypted_secret = self._encrypt_secret(secret)
        
        # Create TOTP instance
        totp = pyotp.TOTP(secret, interval=self.TOTP_PERIOD, digits=self.TOTP_DIGITS)
        
        # Create OTP Auth URL for QR code
        issuer = "FreeCAD CNC Platform"
        account_name = f"{user.email} ({user.full_name or user.email.split('@')[0]})"
        otpauth_url = totp.provisioning_uri(
            name=account_name,
            issuer_name=issuer
        )
        
        # Generate QR code as base64 PNG
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(otpauth_url)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        img_buffer = io.BytesIO()
        img.save(img_buffer, format='PNG')
        img_buffer.seek(0)
        qr_png_base64 = base64.b64encode(img_buffer.read()).decode()
        
        # Store encrypted secret temporarily (not enabled yet)
        user.mfa_secret_encrypted = encrypted_secret
        db.commit()
        
        # Log MFA setup initiation
        audit_log = AuditLog(
            action='mfa_setup_initiated',
            actor_user_id=user.id,
            target_type='User',
            target_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={
                'user_id': user.id,
                'email': user.email,
                'setup_timestamp': datetime.now(timezone.utc).isoformat()
            }
        )
        db.add(audit_log)
        db.commit()
        
        logger.info("MFA setup initiated", extra={
            'user_id': user.id,
            'email': user.email,
            'ip_address': ip_address
        })
        
        # Return setup data (mask secret for security)
        secret_masked = secret[:4] + '*' * (len(secret) - 8) + secret[-4:]
        
        return {
            'secret_masked': secret_masked,
            'otpauth_url': otpauth_url,
            'qr_png_base64': qr_png_base64
        }
    
    def verify_and_enable_mfa(self, db: Session, user: User, code: str,
                             ip_address: Optional[str] = None,
                             user_agent: Optional[str] = None) -> Dict[str, str]:
        """
        Verify TOTP code and enable MFA, generating backup codes.
        """
        if user.mfa_enabled:
            raise MFAError(
                'ERR-MFA-ALREADY-ENABLED',
                'MFA zaten aktif'
            )
        
        if not user.mfa_secret_encrypted:
            raise MFAError(
                'ERR-MFA-SETUP-NOT-STARTED',
                'MFA kurulumu başlatılmamış'
            )
        
        # Check rate limiting
        if not self._check_rate_limit(user.id):
            self._record_verify_attempt(user.id)
            
            # Log rate limit violation
            security_event = SecurityEvent(
                user_id=user.id,
                event_type='mfa_setup_rate_limited',
                ip_address=ip_address,
                user_agent=user_agent,
                details={
                    'user_id': user.id,
                    'email': user.email,
                    'attempts_in_window': len(self._verify_attempts[user.id])
                }
            )
            db.add(security_event)
            db.commit()
            
            raise MFAError(
                'ERR-MFA-RATE-LIMITED',
                'Çok fazla doğrulama denemesi. Lütfen bekleyin.'
            )
        
        # Record attempt
        self._record_verify_attempt(user.id)
        
        # Decrypt and verify TOTP code
        try:
            secret = self._decrypt_secret(user.mfa_secret_encrypted)
            totp = pyotp.TOTP(secret, interval=self.TOTP_PERIOD, digits=self.TOTP_DIGITS)
            
            # Verify with time window tolerance (±1 period)
            is_valid = totp.verify(code, valid_window=1)
            
            if not is_valid:
                # Log failed verification
                security_event = SecurityEvent(
                    user_id=user.id,
                    event_type='mfa_setup_verification_failed',
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details={
                        'user_id': user.id,
                        'email': user.email,
                        'code_provided': len(code)  # Don't log actual code
                    }
                )
                db.add(security_event)
                db.commit()
                
                raise MFAError(
                    'ERR-MFA-INVALID',
                    'MFA kodu geçersiz'
                )
            
            # Enable MFA and generate backup codes
            user.mfa_enabled = True
            user.mfa_enabled_at = datetime.now(timezone.utc)
            
            # Generate backup codes
            backup_codes = self._generate_backup_codes()
            
            # Clear existing backup codes and create new ones
            db.query(MFABackupCode).filter_by(user_id=user.id).delete()
            
            for code in backup_codes:
                backup_code = MFABackupCode(
                    user_id=user.id,
                    code_hash=self._hash_backup_code(code),
                    code_hint=self._create_backup_code_hint(code),
                    expires_at=MFABackupCode.create_expiration_time()
                )
                db.add(backup_code)
            
            user.mfa_backup_codes_count = len(backup_codes)
            db.commit()
            
            # Clear rate limiting for this user
            if user.id in self._verify_attempts:
                del self._verify_attempts[user.id]
            
            # Log successful MFA enablement
            audit_log = AuditLog(
                action='mfa_enabled',
                actor_user_id=user.id,
                target_type='User',
                target_id=user.id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={
                    'user_id': user.id,
                    'email': user.email,
                    'backup_codes_generated': len(backup_codes),
                    'enabled_timestamp': datetime.now(timezone.utc).isoformat()
                }
            )
            db.add(audit_log)
            db.commit()
            
            logger.info("MFA successfully enabled", extra={
                'user_id': user.id,
                'email': user.email,
                'ip_address': ip_address,
                'backup_codes_count': len(backup_codes)
            })
            
            return {
                'message': 'MFA başarıyla etkinleştirildi',
                'backup_codes': backup_codes  # Return once for user to save
            }
            
        except MFAError:
            raise
        except Exception as e:
            logger.error("Unexpected error during MFA verification", exc_info=True, extra={
                'user_id': user.id,
                'email': user.email
            })
            raise MFAError(
                'ERR-MFA-SYSTEM-ERROR',
                'MFA doğrulama sırasında sistem hatası',
                {'error': str(e)}
            )
    
    def verify_totp_code(self, db: Session, user: User, code: str,
                        ip_address: Optional[str] = None,
                        user_agent: Optional[str] = None) -> bool:
        """
        Verify TOTP code for MFA challenge during login.
        """
        if not user.mfa_enabled or not user.mfa_secret_encrypted:
            raise MFAError(
                'ERR-MFA-NOT-ENABLED',
                'MFA aktif değil'
            )
        
        # Check rate limiting
        if not self._check_rate_limit(user.id):
            self._record_verify_attempt(user.id)
            
            # Log rate limit violation
            security_event = SecurityEvent(
                user_id=user.id,
                event_type='mfa_challenge_rate_limited',
                ip_address=ip_address,
                user_agent=user_agent,
                details={
                    'user_id': user.id,
                    'email': user.email,
                    'attempts_in_window': len(self._verify_attempts[user.id])
                }
            )
            db.add(security_event)
            db.commit()
            
            raise MFAError(
                'ERR-MFA-RATE-LIMITED',
                'Çok fazla doğrulama denemesi. Lütfen bekleyin.'
            )
        
        # Record attempt
        self._record_verify_attempt(user.id)
        
        try:
            # Decrypt secret and verify
            secret = self._decrypt_secret(user.mfa_secret_encrypted)
            totp = pyotp.TOTP(secret, interval=self.TOTP_PERIOD, digits=self.TOTP_DIGITS)
            
            # Verify with time window tolerance
            is_valid = totp.verify(code, valid_window=1)
            
            if is_valid:
                # Log successful verification
                audit_log = AuditLog(
                    action='mfa_challenge_succeeded',
                    actor_user_id=user.id,
                    target_type='User',
                    target_id=user.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details={
                        'user_id': user.id,
                        'email': user.email,
                        'verification_timestamp': datetime.now(timezone.utc).isoformat()
                    }
                )
                db.add(audit_log)
                db.commit()
                
                # Clear rate limiting for successful verification
                if user.id in self._verify_attempts:
                    del self._verify_attempts[user.id]
                    
                logger.info("MFA challenge succeeded", extra={
                    'user_id': user.id,
                    'email': user.email,
                    'ip_address': ip_address
                })
                
                return True
            else:
                # Log failed verification
                security_event = SecurityEvent(
                    user_id=user.id,
                    event_type='mfa_challenge_failed',
                    ip_address=ip_address,
                    user_agent=user_agent,
                    details={
                        'user_id': user.id,
                        'email': user.email,
                        'code_length': len(code)  # Don't log actual code
                    }
                )
                db.add(security_event)
                db.commit()
                
                return False
                
        except MFAError:
            raise
        except Exception as e:
            logger.error("Unexpected error during TOTP verification", exc_info=True, extra={
                'user_id': user.id,
                'email': user.email
            })
            return False
    
    def verify_backup_code(self, db: Session, user: User, code: str,
                          ip_address: Optional[str] = None,
                          user_agent: Optional[str] = None) -> bool:
        """
        Verify backup code for MFA challenge.
        """
        if not user.mfa_enabled:
            raise MFAError(
                'ERR-MFA-NOT-ENABLED',
                'MFA aktif değil'
            )
        
        # Check rate limiting
        if not self._check_rate_limit(user.id):
            self._record_verify_attempt(user.id)
            
            security_event = SecurityEvent(
                user_id=user.id,
                event_type='mfa_backup_code_rate_limited',
                ip_address=ip_address,
                user_agent=user_agent,
                details={
                    'user_id': user.id,
                    'email': user.email
                }
            )
            db.add(security_event)
            db.commit()
            
            raise MFAError(
                'ERR-MFA-RATE-LIMITED',
                'Çok fazla doğrulama denemesi. Lütfen bekleyin.'
            )
        
        # Record attempt
        self._record_verify_attempt(user.id)
        
        # Hash the provided code
        code_hash = self._hash_backup_code(code.upper())
        
        # Find matching unused backup code
        backup_code = db.query(MFABackupCode).filter(
            MFABackupCode.user_id == user.id,
            MFABackupCode.code_hash == code_hash,
            MFABackupCode.is_used == False,
            MFABackupCode.expires_at > datetime.now(timezone.utc)
        ).first()
        
        if backup_code:
            # Mark as used
            backup_code.mark_as_used(ip_address, user_agent)
            user.mfa_backup_codes_count -= 1
            db.commit()
            
            # Log successful backup code usage
            audit_log = AuditLog(
                action='backup_code_used',
                actor_user_id=user.id,
                target_type='MFABackupCode',
                target_id=backup_code.id,
                ip_address=ip_address,
                user_agent=user_agent,
                details={
                    'user_id': user.id,
                    'email': user.email,
                    'backup_codes_remaining': user.mfa_backup_codes_count,
                    'code_hint': backup_code.code_hint
                }
            )
            db.add(audit_log)
            
            # Add security event
            security_event = SecurityEvent(
                user_id=user.id,
                event_type='backup_code_used',
                ip_address=ip_address,
                user_agent=user_agent,
                details={
                    'user_id': user.id,
                    'email': user.email,
                    'backup_codes_remaining': user.mfa_backup_codes_count,
                    'code_hint': backup_code.code_hint
                }
            )
            db.add(security_event)
            db.commit()
            
            # Clear rate limiting for successful verification
            if user.id in self._verify_attempts:
                del self._verify_attempts[user.id]
            
            logger.warning("MFA backup code used", extra={
                'user_id': user.id,
                'email': user.email,
                'ip_address': ip_address,
                'backup_codes_remaining': user.mfa_backup_codes_count
            })
            
            return True
        else:
            # Log failed backup code attempt
            security_event = SecurityEvent(
                user_id=user.id,
                event_type='mfa_backup_code_failed',
                ip_address=ip_address,
                user_agent=user_agent,
                details={
                    'user_id': user.id,
                    'email': user.email,
                    'code_length': len(code)  # Don't log actual code
                }
            )
            db.add(security_event)
            db.commit()
            
            return False
    
    def disable_mfa(self, db: Session, user: User, code: str,
                   ip_address: Optional[str] = None,
                   user_agent: Optional[str] = None) -> Dict[str, str]:
        """
        Disable MFA after TOTP verification (not allowed for admin users).
        """
        if not user.mfa_enabled:
            raise MFAError(
                'ERR-MFA-NOT-ENABLED',
                'MFA aktif değil'
            )
        
        if not user.can_disable_mfa():
            raise MFAError(
                'ERR-MFA-ADMIN-REQUIRED',
                'Admin kullanıcılar MFA\'yı devre dışı bırakamaz'
            )
        
        # Verify TOTP code first
        if not self.verify_totp_code(db, user, code, ip_address, user_agent):
            raise MFAError(
                'ERR-MFA-INVALID',
                'MFA kodu geçersiz'
            )
        
        # Disable MFA
        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        user.mfa_enabled_at = None
        user.mfa_backup_codes_count = 0
        
        # Remove all backup codes
        db.query(MFABackupCode).filter_by(user_id=user.id).delete()
        db.commit()
        
        # Log MFA disablement
        audit_log = AuditLog(
            action='mfa_disabled',
            actor_user_id=user.id,
            target_type='User',
            target_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={
                'user_id': user.id,
                'email': user.email,
                'disabled_timestamp': datetime.now(timezone.utc).isoformat()
            }
        )
        db.add(audit_log)
        
        # Add security event
        security_event = SecurityEvent(
            user_id=user.id,
            event_type='mfa_disabled',
            ip_address=ip_address,
            user_agent=user_agent,
            details={
                'user_id': user.id,
                'email': user.email
            }
        )
        db.add(security_event)
        db.commit()
        
        logger.warning("MFA disabled", extra={
            'user_id': user.id,
            'email': user.email,
            'ip_address': ip_address
        })
        
        return {
            'message': 'MFA başarıyla devre dışı bırakıldı'
        }
    
    def regenerate_backup_codes(self, db: Session, user: User,
                               ip_address: Optional[str] = None,
                               user_agent: Optional[str] = None) -> List[str]:
        """
        Generate new backup codes (invalidates old ones).
        """
        if not user.mfa_enabled:
            raise MFAError(
                'ERR-MFA-NOT-ENABLED',
                'MFA aktif değil'
            )
        
        # Generate new backup codes
        backup_codes = self._generate_backup_codes()
        
        # Remove old backup codes
        db.query(MFABackupCode).filter_by(user_id=user.id).delete()
        
        # Create new backup codes
        for code in backup_codes:
            backup_code = MFABackupCode(
                user_id=user.id,
                code_hash=self._hash_backup_code(code),
                code_hint=self._create_backup_code_hint(code),
                expires_at=MFABackupCode.create_expiration_time()
            )
            db.add(backup_code)
        
        user.mfa_backup_codes_count = len(backup_codes)
        db.commit()
        
        # Log backup code regeneration
        audit_log = AuditLog(
            action='backup_codes_regenerated',
            actor_user_id=user.id,
            target_type='User',
            target_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            details={
                'user_id': user.id,
                'email': user.email,
                'codes_generated': len(backup_codes),
                'regenerated_timestamp': datetime.now(timezone.utc).isoformat()
            }
        )
        db.add(audit_log)
        db.commit()
        
        logger.info("MFA backup codes regenerated", extra={
            'user_id': user.id,
            'email': user.email,
            'ip_address': ip_address
        })
        
        return backup_codes


# Global MFA service instance
mfa_service = TOTPService()