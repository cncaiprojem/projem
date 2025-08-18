# Authentication API Reference
## Ultra-Enterprise Banking Grade Authentication System

**Version**: 1.0.0  
**Base URL**: `https://api.freecad-cnc.com.tr/api/v1`  
**Security**: Bearer Token (JWT) + CSRF Double-Submit Cookie  
**Localization**: Turkish (tr-TR) with English fallback  

## Table of Contents

1. [Authentication Overview](#authentication-overview)
2. [Core Authentication APIs](#core-authentication-apis)
3. [JWT Token Management](#jwt-token-management)
4. [OIDC Authentication](#oidc-authentication)
5. [Magic Link Authentication](#magic-link-authentication)
6. [Multi-Factor Authentication](#multi-factor-authentication)
7. [Session Management](#session-management)
8. [Security APIs](#security-apis)
9. [Error Codes](#error-codes)
10. [Rate Limiting](#rate-limiting)

## Authentication Overview

### Security Features
- **Ultra-Enterprise Security**: Banking-level authentication standards
- **Multi-Factor Authentication**: TOTP-based MFA support
- **CSRF Protection**: Double-submit cookie pattern
- **Rate Limiting**: Enterprise-grade request throttling
- **Session Security**: Secure session management with JWT refresh tokens
- **KVKV Compliance**: Turkish data protection compliance

### Cookie Configuration
| Cookie Name | Attributes | Purpose |
|-------------|------------|---------|
| `rt` | HttpOnly, Secure, SameSite=Strict, Max-Age=2592000 | JWT Refresh Token (30 days) |
| `csrf` | Secure, SameSite=Strict, Max-Age=7200 | CSRF Protection Token (2 hours) |

## Core Authentication APIs

### User Registration

**POST** `/auth/register`

Kullanıcı kaydı oluşturur. KVKV uyumlu veri işleme rızası gereklidir.

#### Request Body
```json
{
  "email": "kullanici@example.com",
  "password": "GüçlüŞifre123!",
  "full_name": "Ahmet Yılmaz", 
  "data_processing_consent": true,
  "marketing_consent": false
}
```

#### Request Schema
```typescript
interface UserRegisterRequest {
  email: string;                    // Valid email address
  password: string;                 // Min 12 chars, strong policy
  full_name?: string;               // Optional full name
  data_processing_consent: boolean; // KVKV consent (required: true)
  marketing_consent: boolean;       // Marketing consent (optional)
}
```

#### Response (201 Created)
```json
{
  "user_id": 1,
  "email": "kullanici@example.com",
  "message": "Kayıt başarılı. E-posta doğrulama bağlantısı gönderildi."
}
```

#### cURL Example
```bash
curl -X POST "https://api.freecad-cnc.com.tr/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: abc123..." \
  -d '{
    "email": "test@example.com",
    "password": "StrongPassword123!",
    "full_name": "Test User",
    "data_processing_consent": true,
    "marketing_consent": false
  }'
```

#### Error Responses
- **400 Bad Request**: Validation errors, weak password, existing email
- **429 Too Many Requests**: Registration rate limit exceeded

---

### User Login

**POST** `/auth/login`

Kullanıcı kimlik doğrulaması yapar. Başarısız denemeler hesap kilitleme ile sonuçlanabilir.

#### Request Body
```json
{
  "email": "kullanici@example.com",
  "password": "GüçlüŞifre123!",
  "device_fingerprint": "fp_abc123...",
  "mfa_code": "123456"
}
```

#### Request Schema
```typescript
interface UserLoginRequest {
  email: string;                // User email address
  password: string;             // User password
  device_fingerprint?: string;  // Optional device fingerprint
  mfa_code?: string;           // MFA code (if required)
}
```

#### Response (200 OK)
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900,
  "user_id": 1,
  "email": "kullanici@example.com",
  "full_name": "Ahmet Yılmaz",
  "role": "user",
  "mfa_required": false,
  "password_must_change": false
}
```

#### MFA Challenge Response (200 OK)
```json
{
  "access_token": "mfa_challenge_required",
  "token_type": "mfa_challenge", 
  "expires_in": 300,
  "user_id": 1,
  "email": "kullanici@example.com",
  "mfa_required": true,
  "password_must_change": false
}
```

#### cURL Example
```bash
curl -X POST "https://api.freecad-cnc.com.tr/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: abc123..." \
  -c cookies.txt \
  -d '{
    "email": "test@example.com",
    "password": "StrongPassword123!",
    "device_fingerprint": "fp_device123"
  }'
```

#### Error Responses
- **400 Bad Request**: Invalid credentials, account locked
- **429 Too Many Requests**: Login rate limit exceeded

---

### Password Strength Check

**POST** `/auth/password/strength`

Şifre gücünü ve politika uyumluluğunu kontrol eder.

#### Request Body
```json
{
  "password": "TestPassword123!"
}
```

#### Response (200 OK)
```json
{
  "score": 85,
  "ok": true,
  "feedback": [
    "Şifre gücü yeterli",
    "Büyük harf, küçük harf, sayı ve özel karakter içeriyor"
  ]
}
```

#### cURL Example
```bash
curl -X POST "https://api.freecad-cnc.com.tr/api/v1/auth/password/strength" \
  -H "Content-Type: application/json" \
  -d '{"password": "TestPassword123!"}'
```

---

### Password Reset Flow

#### Forgot Password

**POST** `/auth/password/forgot`

Şifre sıfırlama sürecini başlatır. Güvenlik için her zaman başarılı yanıt verir.

#### Request Body
```json
{
  "email": "kullanici@example.com"
}
```

#### Response (202 Accepted)
```json
{
  "message": "Şifre sıfırlama bağlantısı e-posta adresinize gönderildi."
}
```

#### cURL Example
```bash
curl -X POST "https://api.freecad-cnc.com.tr/api/v1/auth/password/forgot" \
  -H "Content-Type: application/json" \
  -H "X-CSRF-Token: abc123..." \
  -d '{"email": "test@example.com"}'
```

#### Reset Password

**POST** `/auth/password/reset`

Şifre sıfırlama token'ı ile yeni şifre belirleme.

#### Request Body
```json
{
  "token": "reset_token_from_email",
  "new_password": "YeniGüçlüŞifre456!"
}
```

#### Response (200 OK)
```json
{
  "message": "Şifre başarıyla güncellendi.",
  "user_id": 1
}
```

---

### User Profile

**GET** `/auth/me`

Mevcut kullanıcının profil bilgilerini getirir.

**Authentication Required**: Bearer token

#### Response (200 OK)
```json
{
  "user_id": 1,
  "email": "kullanici@example.com",
  "full_name": "Ahmet Yılmaz",
  "display_name": "Ahmet Y.",
  "role": "user",
  "account_status": "active",
  "is_email_verified": true,
  "locale": "tr-TR",
  "timezone": "Europe/Istanbul",
  "created_at": "2025-01-01T00:00:00Z",
  "last_login_at": "2025-01-15T10:30:00Z",
  "total_login_count": 42,
  "data_processing_consent": true,
  "marketing_consent": false
}
```

#### cURL Example
```bash
curl -X GET "https://api.freecad-cnc.com.tr/api/v1/auth/me" \
  -H "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

## JWT Token Management

### Refresh Token

**POST** `/auth-jwt/refresh`

Yeni access token almak için refresh token kullanır.

**Authentication**: Refresh token in httpOnly cookie

#### Response (200 OK)
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900,
  "user_id": 1,
  "email": "kullanici@example.com",
  "role": "user"
}
```

#### cURL Example
```bash
curl -X POST "https://api.freecad-cnc.com.tr/api/v1/auth-jwt/refresh" \
  -H "X-CSRF-Token: abc123..." \
  -b cookies.txt
```

### Revoke Session

**POST** `/auth-jwt/revoke`

Mevcut oturumu sonlandırır ve refresh token'ı geçersiz kılar.

**Authentication**: Bearer token + Refresh token cookie

#### Response (200 OK)
```json
{
  "message": "Oturum başarıyla sonlandırıldı"
}
```

### Revoke All Sessions

**POST** `/auth-jwt/revoke-all`

Kullanıcının tüm aktif oturumlarını sonlandırır.

**Authentication**: Bearer token

#### Response (200 OK)  
```json
{
  "message": "Tüm oturumlar başarıyla sonlandırıldı",
  "revoked_sessions": 3
}
```

---

## OIDC Authentication

### Google OIDC Login

**GET** `/oidc/google/login`

Google OIDC kimlik doğrulama sürecini başlatır.

#### Query Parameters
- `redirect_uri` (optional): Post-login redirect URL

#### Response (302 Redirect)
Redirects to Google OAuth consent screen.

#### cURL Example
```bash
curl -X GET "https://api.freecad-cnc.com.tr/api/v1/oidc/google/login?redirect_uri=https://app.freecad-cnc.com.tr/dashboard"
```

### Google OIDC Callback

**GET** `/oidc/google/callback`

Google OIDC kimlik doğrulama geri dönüş endpoint'i.

#### Query Parameters
- `code`: Authorization code from Google
- `state`: CSRF state parameter

#### Response (302 Redirect)
Redirects to application with authentication result.

---

## Magic Link Authentication

### Request Magic Link

**POST** `/magic-link/request`

Magic link e-posta gönderim talebi.

#### Request Body
```json
{
  "email": "kullanici@example.com"
}
```

#### Response (202 Accepted)
```json
{
  "message": "Magic link e-posta adresinize gönderildi."
}
```

### Verify Magic Link

**GET** `/magic-link/verify/{token}`

Magic link token doğrulama.

#### Path Parameters
- `token`: Magic link token from email

#### Response (200 OK)
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 900,
  "user": {
    "user_id": 1,
    "email": "kullanici@example.com",
    "full_name": "Ahmet Yılmaz"
  }
}
```

---

## Multi-Factor Authentication

### Setup TOTP

**POST** `/mfa/totp/setup`

TOTP MFA kurulum sürecini başlatır.

**Authentication**: Bearer token

#### Response (200 OK)
```json
{
  "secret": "JBSWY3DPEHPK3PXP",
  "qr_code_url": "otpauth://totp/FreeCAD%20CNC:kullanici@example.com?secret=JBSWY3DPEHPK3PXP&issuer=FreeCAD%20CNC",
  "backup_codes": [
    "12345678",
    "23456789",
    "34567890"
  ]
}
```

### Verify TOTP Setup

**POST** `/mfa/totp/verify-setup`

TOTP kurulumunu doğrular ve aktifleştirir.

#### Request Body
```json
{
  "totp_code": "123456"
}
```

#### Response (200 OK)
```json
{
  "message": "TOTP başarıyla aktifleştirildi",
  "backup_codes": [
    "12345678",
    "23456789"
  ]
}
```

### Disable TOTP

**POST** `/mfa/totp/disable`

TOTP MFA'yı devre dışı bırakır.

#### Request Body
```json
{
  "totp_code": "123456"
}
```

#### Response (200 OK)
```json
{
  "message": "TOTP başarıyla devre dışı bırakıldı"
}
```

---

## Security APIs

### Get CSRF Token

**GET** `/auth/csrf-token`

Browser istekleri için CSRF double-submit cookie token'ı oluşturur.

#### Response (200 OK)
```json
{
  "message": "CSRF token başarıyla oluşturuldu",
  "details": {
    "tr": "CSRF token'ı cookie olarak ayarlandı. Frontend X-CSRF-Token header'ında kullanabilir.",
    "en": "CSRF token set as cookie. Frontend can use in X-CSRF-Token header.",
    "cookie_name": "csrf",
    "header_name": "X-CSRF-Token",
    "expires_in_seconds": 7200,
    "usage": "State-changing isteklerde (POST, PUT, PATCH, DELETE) gerekli"
  }
}
```

#### cURL Example
```bash
curl -X GET "https://api.freecad-cnc.com.tr/api/v1/auth/csrf-token" \
  -c csrf-cookies.txt
```

---

## Error Codes

### Authentication Error Codes

| Error Code | Turkish Message | English Message | HTTP Status |
|------------|-----------------|-----------------|-------------|
| ERR-AUTH-EMAIL-EXISTS | E-posta adresi zaten kullanımda | Email address already in use | 400 |
| ERR-AUTH-WEAK-PASSWORD | Şifre yeterince güçlü değil | Password is not strong enough | 400 |
| ERR-AUTH-INVALID-CREDENTIALS | Geçersiz e-posta veya şifre | Invalid email or password | 400 |
| ERR-AUTH-ACCOUNT-LOCKED | Hesap güvenlik nedeniyle kilitlendi | Account locked for security reasons | 400 |
| ERR-AUTH-MFA-REQUIRED | İki faktörlü doğrulama gerekli | Two-factor authentication required | 400 |
| ERR-AUTH-MFA-INVALID | Geçersiz MFA kodu | Invalid MFA code | 400 |
| ERR-AUTH-TOKEN-EXPIRED | Token süresi doldu | Token has expired | 401 |
| ERR-AUTH-TOKEN-INVALID | Geçersiz token | Invalid token | 401 |
| ERR-AUTH-INSUFFICIENT-PERMISSIONS | Yetersiz yetki | Insufficient permissions | 403 |
| ERR-AUTH-SYSTEM-ERROR | Sistem hatası | System error | 500 |

### CSRF Error Codes

| Error Code | Turkish Message | HTTP Status |
|------------|-----------------|-------------|
| ERR-CSRF-TOKEN-MISSING | CSRF token eksik | 403 |
| ERR-CSRF-TOKEN-INVALID | Geçersiz CSRF token | 403 |
| ERR-CSRF-TOKEN-EXPIRED | CSRF token süresi doldu | 403 |

### Rate Limiting Error Codes

| Error Code | Turkish Message | HTTP Status |
|------------|-----------------|-------------|
| ERR-RATE-LIMIT-EXCEEDED | İstek limiti aşıldı | 429 |
| ERR-RATE-LIMIT-LOGIN | Giriş denemesi limiti aşıldı | 429 |
| ERR-RATE-LIMIT-REGISTRATION | Kayıt denemesi limiti aşıldı | 429 |

---

## Rate Limiting

### Authentication Endpoints

| Endpoint | Rate Limit | Window | Scope |
|----------|------------|--------|-------|
| `/auth/login` | 5 attempts | 15 minutes | per IP + email |
| `/auth/register` | 3 attempts | 1 hour | per IP |
| `/auth/password/forgot` | 3 attempts | 1 hour | per IP + email |
| `/auth/password/strength` | 20 attempts | 1 minute | per IP |
| `/auth/csrf-token` | 60 attempts | 1 minute | per IP |

### JWT Endpoints

| Endpoint | Rate Limit | Window | Scope |
|----------|------------|--------|-------|
| `/auth-jwt/refresh` | 30 attempts | 1 minute | per refresh token |
| `/auth-jwt/revoke` | 10 attempts | 1 minute | per user |

### Rate Limit Headers

```
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 3
X-RateLimit-Reset: 1642684800
X-RateLimit-Retry-After: 900
```

---

## Security Headers

All API responses include comprehensive security headers:

```
Content-Security-Policy: default-src 'self'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
Cross-Origin-Embedder-Policy: require-corp
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Resource-Policy: same-origin
```

---

## Integration Examples

### Frontend Login Flow
```javascript
// 1. Get CSRF token
const csrfResponse = await fetch('/api/v1/auth/csrf-token', {
  credentials: 'include'
});

// 2. Login with CSRF token
const loginResponse = await fetch('/api/v1/auth/login', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-CSRF-Token': getCookieValue('csrf')
  },
  credentials: 'include',
  body: JSON.stringify({
    email: 'user@example.com',
    password: 'password123'
  })
});

const { access_token } = await loginResponse.json();

// 3. Use access token for authenticated requests
const userResponse = await fetch('/api/v1/auth/me', {
  headers: {
    'Authorization': `Bearer ${access_token}`
  }
});
```

### Refresh Token Flow
```javascript
// Automatic token refresh
let accessToken = localStorage.getItem('access_token');

const apiCall = async (url, options = {}) => {
  const response = await fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${accessToken}`
    }
  });
  
  if (response.status === 401) {
    // Token expired, refresh
    const refreshResponse = await fetch('/api/v1/auth-jwt/refresh', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'X-CSRF-Token': getCookieValue('csrf')
      }
    });
    
    if (refreshResponse.ok) {
      const { access_token } = await refreshResponse.json();
      accessToken = access_token;
      localStorage.setItem('access_token', access_token);
      
      // Retry original request
      return fetch(url, {
        ...options,
        headers: {
          ...options.headers,
          'Authorization': `Bearer ${accessToken}`
        }
      });
    } else {
      // Refresh failed, redirect to login
      window.location.href = '/login';
    }
  }
  
  return response;
};
```

---

## Testing

### Authentication Test Suite
```bash
# Run all authentication tests
pytest apps/api/tests/integration/test_auth_endpoints.py -v

# Test specific authentication flows
pytest apps/api/tests/test_oidc_auth.py -v
pytest apps/api/tests/test_magic_link.py -v
pytest apps/api/tests/test_mfa_integration.py -v

# Security tests
pytest apps/api/tests/security/ -v
```

### Manual Testing with cURL
```bash
# Complete authentication flow
# 1. Register
curl -X POST "http://localhost:8000/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"StrongPass123!","data_processing_consent":true}'

# 2. Login
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d '{"email":"test@example.com","password":"StrongPass123!"}'

# 3. Access protected resource
curl -X GET "http://localhost:8000/api/v1/auth/me" \
  -H "Authorization: Bearer <access_token>"

# 4. Refresh token
curl -X POST "http://localhost:8000/api/v1/auth-jwt/refresh" \
  -b cookies.txt
```

---

**📝 Not**: Bu API dokümantasyonu sürekli güncellenmektedir. En güncel sürüm için [GitHub repository](https://github.com/shaptina/projem)'yi kontrol edin.

**🔒 Güvenlik**: Tüm API endpoint'leri HTTPS üzerinden erişilmelidir. Production ortamında HTTP trafiği otomatik olarak HTTPS'e yönlendirilir.