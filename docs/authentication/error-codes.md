# Error Code Reference
## Canonical ERR-* Codes for Ultra-Enterprise Authentication System

**Version**: 1.0.0  
**Last Updated**: 2025-08-18  
**Compliance**: Turkish KVKV, Banking Standards  

## Overview

This document provides a comprehensive reference of all error codes used in the ultra-enterprise authentication system. All error codes follow the pattern `ERR-{CATEGORY}-{SPECIFIC_ERROR}` and include both Turkish and English messages for KVKV compliance.

## Error Code Structure

```
ERR-{CATEGORY}-{SPECIFIC_ERROR}
```

- **ERR**: Error prefix (constant)
- **CATEGORY**: Error category (AUTH, CSRF, RATE, MFA, etc.)
- **SPECIFIC_ERROR**: Specific error type

## Authentication Error Codes (ERR-AUTH-*)

### Registration Errors

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-AUTH-EMAIL-EXISTS` | E-posta adresi zaten kullanımda | Email address already in use | 400 | Email already registered in system |
| `ERR-AUTH-WEAK-PASSWORD` | Şifre yeterince güçlü değil | Password is not strong enough | 400 | Password doesn't meet strength requirements |
| `ERR-AUTH-INVALID-EMAIL` | Geçersiz e-posta formatı | Invalid email format | 400 | Email format validation failed |
| `ERR-AUTH-MISSING-CONSENT` | KVKK veri işleme rızası zorunludur | KVKV data processing consent required | 400 | Required KVKV consent not provided |
| `ERR-AUTH-REGISTRATION-DISABLED` | Yeni kayıt kapalı | New registration disabled | 403 | Registration temporarily disabled |

### Login Errors

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-AUTH-INVALID-CREDENTIALS` | Geçersiz e-posta veya şifre | Invalid email or password | 400 | Authentication credentials invalid |
| `ERR-AUTH-ACCOUNT-LOCKED` | Hesap güvenlik nedeniyle kilitlendi | Account locked for security reasons | 423 | Account locked due to multiple failed attempts |
| `ERR-AUTH-ACCOUNT-DISABLED` | Hesap devre dışı bırakıldı | Account has been disabled | 423 | Account administratively disabled |
| `ERR-AUTH-EMAIL-NOT-VERIFIED` | E-posta adresi doğrulanmamış | Email address not verified | 403 | Email verification required |
| `ERR-AUTH-PASSWORD-EXPIRED` | Şifre süresi doldu | Password has expired | 403 | Password change required |
| `ERR-AUTH-TEMPORARY-LOCKOUT` | Geçici hesap kilidi aktif | Temporary account lockout active | 423 | Temporary lockout in effect |

### Token Management Errors

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-AUTH-TOKEN-EXPIRED` | Token süresi doldu | Token has expired | 401 | JWT access token expired |
| `ERR-AUTH-TOKEN-INVALID` | Geçersiz token | Invalid token | 401 | JWT token invalid or malformed |
| `ERR-AUTH-TOKEN-REVOKED` | Token iptal edildi | Token has been revoked | 401 | Token has been revoked |
| `ERR-AUTH-REFRESH-TOKEN-EXPIRED` | Refresh token süresi doldu | Refresh token has expired | 401 | Refresh token expired |
| `ERR-AUTH-REFRESH-TOKEN-INVALID` | Geçersiz refresh token | Invalid refresh token | 401 | Refresh token invalid |
| `ERR-AUTH-TOKEN-REUSE-DETECTED` | Token tekrar kullanım tespit edildi | Token reuse detected | 401 | Suspicious token reuse detected |

### Authorization Errors

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-AUTH-INSUFFICIENT-PERMISSIONS` | Yetersiz yetki | Insufficient permissions | 403 | User lacks required permissions |
| `ERR-AUTH-ROLE-NOT-AUTHORIZED` | Bu rol için yetki yok | Role not authorized for this action | 403 | User role not authorized |
| `ERR-AUTH-RESOURCE-ACCESS-DENIED` | Kaynak erişimi reddedildi | Resource access denied | 403 | Access to specific resource denied |
| `ERR-AUTH-ADMIN-REQUIRED` | Yönetici yetkisi gerekli | Administrator privileges required | 403 | Admin-level access required |

### Password Management Errors

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-AUTH-PASSWORD-RESET-TOKEN-EXPIRED` | Şifre sıfırlama token süresi doldu | Password reset token expired | 400 | Reset token expired (1 hour limit) |
| `ERR-AUTH-PASSWORD-RESET-TOKEN-INVALID` | Geçersiz şifre sıfırlama token | Invalid password reset token | 400 | Reset token invalid or malformed |
| `ERR-AUTH-PASSWORD-RESET-TOKEN-USED` | Şifre sıfırlama token kullanılmış | Password reset token already used | 400 | Reset token already consumed |
| `ERR-AUTH-PASSWORD-SAME-AS-CURRENT` | Yeni şifre mevcut şifreyle aynı | New password same as current | 400 | New password must be different |
| `ERR-AUTH-PASSWORD-RECENTLY-USED` | Şifre son zamanlarda kullanılmış | Password recently used | 400 | Password in recent history |

### System Errors

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-AUTH-SYSTEM-ERROR` | Sistem hatası, lütfen tekrar deneyin | System error, please try again | 500 | Internal authentication system error |
| `ERR-AUTH-DATABASE-ERROR` | Veritabanı hatası | Database error | 500 | Database connection or query error |
| `ERR-AUTH-EMAIL-SERVICE-ERROR` | E-posta servisi hatası | Email service error | 503 | Email sending service unavailable |
| `ERR-AUTH-CRYPTO-ERROR` | Kriptografi hatası | Cryptographic error | 500 | Encryption/decryption error |

---

## CSRF Error Codes (ERR-CSRF-*)

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-CSRF-TOKEN-MISSING` | CSRF token eksik | CSRF token missing | 403 | Required CSRF token not provided |
| `ERR-CSRF-TOKEN-INVALID` | Geçersiz CSRF token | Invalid CSRF token | 403 | CSRF token validation failed |
| `ERR-CSRF-TOKEN-EXPIRED` | CSRF token süresi doldu | CSRF token expired | 403 | CSRF token expired (2 hour limit) |
| `ERR-CSRF-TOKEN-MISMATCH` | CSRF token uyuşmazlığı | CSRF token mismatch | 403 | Cookie and header token mismatch |
| `ERR-CSRF-DOUBLE-SUBMIT-FAILED` | CSRF çift gönderim doğrulaması başarısız | CSRF double submit validation failed | 403 | Double-submit cookie pattern failed |
| `ERR-CSRF-TOKEN-FAILED` | CSRF token oluşturma başarısız | Failed to generate CSRF token | 500 | CSRF token generation error |

---

## Rate Limiting Error Codes (ERR-RATE-*)

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-RATE-LIMIT-EXCEEDED` | İstek limiti aşıldı | Request rate limit exceeded | 429 | General rate limit exceeded |
| `ERR-RATE-LIMIT-LOGIN` | Giriş denemesi limiti aşıldı | Login attempt rate limit exceeded | 429 | Too many login attempts |
| `ERR-RATE-LIMIT-REGISTRATION` | Kayıt denemesi limiti aşıldı | Registration rate limit exceeded | 429 | Too many registration attempts |
| `ERR-RATE-LIMIT-PASSWORD-RESET` | Şifre sıfırlama limiti aşıldı | Password reset rate limit exceeded | 429 | Too many password reset requests |
| `ERR-RATE-LIMIT-MFA` | MFA denemesi limiti aşıldı | MFA attempt rate limit exceeded | 429 | Too many MFA attempts |
| `ERR-RATE-LIMIT-CSRF` | CSRF token limiti aşıldı | CSRF token rate limit exceeded | 429 | Too many CSRF token requests |
| `ERR-RATE-LIMIT-API` | API istek limiti aşıldı | API request rate limit exceeded | 429 | General API rate limit exceeded |

---

## Multi-Factor Authentication Error Codes (ERR-MFA-*)

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-MFA-REQUIRED` | İki faktörlü doğrulama gerekli | Two-factor authentication required | 400 | MFA verification required |
| `ERR-MFA-INVALID-CODE` | Geçersiz MFA kodu | Invalid MFA code | 400 | TOTP code invalid or expired |
| `ERR-MFA-CODE-EXPIRED` | MFA kodu süresi doldu | MFA code expired | 400 | TOTP code time window expired |
| `ERR-MFA-CODE-REUSED` | MFA kodu tekrar kullanıldı | MFA code reused | 400 | TOTP code already used |
| `ERR-MFA-NOT-ENABLED` | MFA etkinleştirilmemiş | MFA not enabled | 400 | MFA not set up for user |
| `ERR-MFA-ALREADY-ENABLED` | MFA zaten etkinleştirilmiş | MFA already enabled | 400 | MFA already configured |
| `ERR-MFA-BACKUP-CODE-INVALID` | Geçersiz yedek kod | Invalid backup code | 400 | Backup code invalid or used |
| `ERR-MFA-SETUP-TOKEN-INVALID` | Geçersiz MFA kurulum token | Invalid MFA setup token | 400 | MFA setup session invalid |

---

## OIDC Authentication Error Codes (ERR-OIDC-*)

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-OIDC-INVALID-STATE` | Geçersiz OIDC state parametresi | Invalid OIDC state parameter | 400 | State parameter validation failed |
| `ERR-OIDC-CODE-EXCHANGE-FAILED` | OIDC kod değişimi başarısız | OIDC code exchange failed | 400 | Authorization code exchange failed |
| `ERR-OIDC-TOKEN-VALIDATION-FAILED` | OIDC token doğrulaması başarısız | OIDC token validation failed | 400 | ID token validation failed |
| `ERR-OIDC-USER-INFO-FAILED` | OIDC kullanıcı bilgisi alınamadı | OIDC user info retrieval failed | 400 | User info endpoint failed |
| `ERR-OIDC-EMAIL-NOT-VERIFIED` | OIDC e-posta doğrulanmamış | OIDC email not verified | 400 | Provider email not verified |
| `ERR-OIDC-PROVIDER-ERROR` | OIDC sağlayıcı hatası | OIDC provider error | 502 | External OIDC provider error |
| `ERR-OIDC-CONFIG-ERROR` | OIDC yapılandırma hatası | OIDC configuration error | 500 | OIDC configuration invalid |

---

## Magic Link Error Codes (ERR-MAGIC-*)

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-MAGIC-LINK-EXPIRED` | Magic link süresi doldu | Magic link expired | 400 | Magic link expired (15 minutes) |
| `ERR-MAGIC-LINK-INVALID` | Geçersiz magic link | Invalid magic link | 400 | Magic link token invalid |
| `ERR-MAGIC-LINK-USED` | Magic link kullanılmış | Magic link already used | 400 | Magic link already consumed |
| `ERR-MAGIC-LINK-EMAIL-FAILED` | Magic link e-postası gönderilemedi | Magic link email failed to send | 503 | Email delivery failed |
| `ERR-MAGIC-LINK-DISABLED` | Magic link giriş devre dışı | Magic link login disabled | 403 | Magic link feature disabled |

---

## Session Management Error Codes (ERR-SESSION-*)

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-SESSION-NOT-FOUND` | Oturum bulunamadı | Session not found | 401 | Session doesn't exist or expired |
| `ERR-SESSION-EXPIRED` | Oturum süresi doldu | Session expired | 401 | Session exceeded maximum lifetime |
| `ERR-SESSION-INVALID` | Geçersiz oturum | Invalid session | 401 | Session data corrupted or invalid |
| `ERR-SESSION-CONCURRENT-LIMIT` | Eşzamanlı oturum limiti aşıldı | Concurrent session limit exceeded | 429 | Too many active sessions |
| `ERR-SESSION-DEVICE-MISMATCH` | Cihaz uyuşmazlığı | Device fingerprint mismatch | 401 | Session device doesn't match |
| `ERR-SESSION-IP-MISMATCH` | IP adresi uyuşmazlığı | IP address mismatch | 401 | Session IP doesn't match |

---

## Input Validation Error Codes (ERR-INPUT-*)

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-INPUT-XSS-DETECTED` | Potansiyel XSS saldırısı tespit edildi | Potential XSS attack detected | 400 | XSS pattern in input |
| `ERR-INPUT-SQL-INJECTION-DETECTED` | Potansiyel SQL enjeksiyonu tespit edildi | Potential SQL injection detected | 400 | SQL injection pattern detected |
| `ERR-INPUT-MALICIOUS-CONTENT` | Şüpheli içerik tespit edildi | Malicious content detected | 400 | Multiple threat indicators |
| `ERR-INPUT-FILE-TOO-LARGE` | Dosya çok büyük | File too large | 413 | File size exceeds limit |
| `ERR-INPUT-INVALID-FILE-TYPE` | Geçersiz dosya türü | Invalid file type | 400 | File type not allowed |
| `ERR-INPUT-SANITIZATION-FAILED` | Girdi temizleme başarısız | Input sanitization failed | 500 | Sanitization process failed |

---

## License Management Error Codes (ERR-LICENSE-*)

| Code | Turkish Message | English Message | HTTP Status | Details |
|------|-----------------|-----------------|-------------|---------|
| `ERR-LICENSE-EXPIRED` | Lisans süresi doldu | License expired | 402 | Software license expired |
| `ERR-LICENSE-INVALID` | Geçersiz lisans | Invalid license | 402 | License key invalid |
| `ERR-LICENSE-USER-LIMIT-EXCEEDED` | Kullanıcı limiti aşıldı | User limit exceeded | 402 | License user limit reached |
| `ERR-LICENSE-FEATURE-NOT-LICENSED` | Özellik lisanslanmamış | Feature not licensed | 402 | Feature requires license upgrade |
| `ERR-LICENSE-VERIFICATION-FAILED` | Lisans doğrulaması başarısız | License verification failed | 502 | License server unavailable |

---

## Error Response Format

### Standard Error Response Structure

```json
{
  "error_code": "ERR-AUTH-INVALID-CREDENTIALS",
  "message": "Geçersiz e-posta veya şifre",
  "details": {
    "tr": "Girdiğiniz e-posta veya şifre hatalı. Lütfen kontrol edip tekrar deneyin.",
    "en": "The email or password you entered is incorrect. Please check and try again.",
    "field": "credentials",
    "timestamp": "2025-01-15T10:30:00Z",
    "request_id": "req_abc123",
    "retry_after": null
  }
}
```

### Rate Limit Error Response

```json
{
  "error_code": "ERR-RATE-LIMIT-LOGIN",
  "message": "Giriş denemesi limiti aşıldı",
  "details": {
    "tr": "Çok fazla başarısız giriş denemesi. 15 dakika sonra tekrar deneyin.",
    "en": "Too many failed login attempts. Please try again in 15 minutes.",
    "retry_after": 900,
    "reset_time": "2025-01-15T10:45:00Z",
    "limit": 5,
    "remaining": 0
  }
}
```

### Validation Error Response

```json
{
  "error_code": "ERR-AUTH-WEAK-PASSWORD",
  "message": "Şifre yeterince güçlü değil",
  "details": {
    "tr": "Şifre en az 12 karakter olmalı ve büyük harf, küçük harf, sayı ve özel karakter içermelidir.",
    "en": "Password must be at least 12 characters and contain uppercase, lowercase, number and special character.",
    "validation_errors": [
      "Minimum 12 karakter gerekli",
      "Büyük harf eksik",
      "Özel karakter eksik"
    ],
    "strength_score": 35
  }
}
```

---

## Error Code Categories Summary

| Category | Prefix | Count | Description |
|----------|--------|-------|-------------|
| Authentication | `ERR-AUTH-*` | 25 | Core authentication errors |
| CSRF Protection | `ERR-CSRF-*` | 6 | CSRF token validation errors |
| Rate Limiting | `ERR-RATE-*` | 7 | Request rate limiting errors |
| Multi-Factor Auth | `ERR-MFA-*` | 8 | MFA-related errors |
| OIDC | `ERR-OIDC-*` | 7 | OAuth/OIDC provider errors |
| Magic Link | `ERR-MAGIC-*` | 5 | Magic link authentication errors |
| Session Management | `ERR-SESSION-*` | 6 | Session handling errors |
| Input Validation | `ERR-INPUT-*` | 6 | Input security validation errors |
| License Management | `ERR-LICENSE-*` | 5 | Software licensing errors |
| **Total** | | **75** | **All error codes** |

---

## Error Handling Best Practices

### Client-Side Error Handling

```javascript
const handleApiError = (error) => {
  const { error_code, message, details } = error;
  
  switch (error_code) {
    case 'ERR-AUTH-INVALID-CREDENTIALS':
      showError('Giriş bilgilerinizi kontrol edin');
      clearPasswordField();
      break;
      
    case 'ERR-AUTH-ACCOUNT-LOCKED':
      showError('Hesabınız güvenlik nedeniyle kilitlendi');
      redirectToSupport();
      break;
      
    case 'ERR-RATE-LIMIT-LOGIN':
      showError(`Çok fazla deneme. ${details.retry_after} saniye bekleyin.`);
      startCountdownTimer(details.retry_after);
      break;
      
    case 'ERR-AUTH-MFA-REQUIRED':
      redirectToMFAPage();
      break;
      
    default:
      showError(message);
  }
};
```

### Server-Side Error Logging

```python
def log_authentication_error(error_code: str, details: dict):
    """Log authentication errors for security monitoring."""
    logger.warning(
        "Authentication error occurred",
        extra={
            'operation': 'authentication_error',
            'error_code': error_code,
            'client_ip': details.get('client_ip'),
            'user_agent': details.get('user_agent'),
            'email': details.get('email_hash'),  # Hashed email for privacy
            'timestamp': datetime.utcnow().isoformat(),
            'correlation_id': details.get('correlation_id')
        }
    )
    
    # Trigger security alerts for critical errors
    if error_code in CRITICAL_ERROR_CODES:
        trigger_security_alert(error_code, details)
```

---

## Monitoring and Alerting

### Error Code Monitoring

Monitor these error codes for security incidents:

**Critical Alerts (Immediate)**:
- `ERR-AUTH-TOKEN-REUSE-DETECTED`
- `ERR-INPUT-XSS-DETECTED`
- `ERR-INPUT-SQL-INJECTION-DETECTED`
- `ERR-SESSION-DEVICE-MISMATCH`
- `ERR-CSRF-DOUBLE-SUBMIT-FAILED`

**Warning Alerts (Within 15 minutes)**:
- High frequency of `ERR-AUTH-INVALID-CREDENTIALS`
- Multiple `ERR-RATE-LIMIT-*` errors
- `ERR-AUTH-ACCOUNT-LOCKED` patterns
- `ERR-MFA-INVALID-CODE` brute force attempts

**Info Alerts (Daily summary)**:
- `ERR-AUTH-WEAK-PASSWORD` trends
- `ERR-LICENSE-*` errors
- `ERR-MAGIC-LINK-*` delivery issues

### Dashboards

Create monitoring dashboards for:
1. **Authentication Error Trends**: Track error frequency over time
2. **Security Threat Detection**: Monitor malicious activity patterns  
3. **System Health**: Track system-level authentication errors
4. **User Experience**: Monitor user-facing authentication issues

---

## Compliance Notes

### Turkish KVKV Compliance
- All error messages provided in Turkish
- User data privacy maintained in error details
- Security incident logging for audit purposes
- Data processing consent validation in registration

### Banking Security Standards
- Comprehensive error categorization
- Detailed audit trail for all errors
- Rate limiting to prevent abuse
- Multi-layered security validation

### GDPR Compliance
- Minimal data exposure in error messages
- User privacy protected in logging
- Clear consent validation
- Right to be forgotten support

---

**📝 Güncellemeler**: Bu error code referansı sistem güncellemeleriyle birlikte sürekli güncellenmektedir.

**🚨 Güvenlik**: Error code'lar güvenlik monitoring sistemine entegre edilmiştir. Kritik hatalar otomatik olarak güvenlik ekibine bildirilir.