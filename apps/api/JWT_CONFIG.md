# JWT Configuration Guide for Task 3.3

This document provides the complete configuration guide for the ultra enterprise JWT authentication system implemented in Task 3.3.

## Environment Variables

### Core JWT Configuration

```bash
# JWT Secret Key (CRITICAL SECURITY)
JWT_SECRET_KEY="your-ultra-secure-jwt-secret-minimum-32-chars-here"
# If not set, falls back to SECRET_KEY

# JWT Algorithm (Default: HS256)
JWT_ALGORITHM="HS256"

# Access Token Expiration (minutes)
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30

# Refresh Token Expiration (days)
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# JWT Issuer
JWT_ISSUER="freecad-api"

# JWT Audience
JWT_AUDIENCE="freecad-users"
```

### Refresh Token Security

```bash
# Refresh Token Length (bytes, 64 = 512 bits)
REFRESH_TOKEN_LENGTH=64

# Refresh Token Cookie Configuration
REFRESH_TOKEN_COOKIE_NAME="rt"
REFRESH_TOKEN_COOKIE_DOMAIN=""  # Set for production (e.g., ".yourdomain.com")
REFRESH_TOKEN_COOKIE_SECURE=true
REFRESH_TOKEN_COOKIE_SAMESITE="strict"

# Additional Token Security
REFRESH_TOKEN_SECRET="separate-secret-for-refresh-token-hmac"
# If not set, falls back to SECRET_KEY
```

### Development Environment (.env.example)

```bash
# === JWT Authentication Configuration ===
SECRET_KEY="dev-secret-key-minimum-32-characters-long-for-security"
JWT_SECRET_KEY="dev-jwt-secret-key-minimum-32-chars-long"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
JWT_ISSUER="freecad-api"
JWT_AUDIENCE="freecad-users"

# Refresh Token Configuration
REFRESH_TOKEN_LENGTH=64
REFRESH_TOKEN_COOKIE_NAME="rt"
REFRESH_TOKEN_COOKIE_SECURE=false  # false for development, true for production
REFRESH_TOKEN_COOKIE_SAMESITE="strict"

# Session Configuration
SESSION_SECRET="dev-session-secret-for-hmac-operations"
MAX_SESSIONS_PER_USER=10
```

### Production Environment

```bash
# === PRODUCTION JWT Configuration ===
SECRET_KEY="CHANGE-THIS-TO-ULTRA-SECURE-RANDOM-SECRET-MINIMUM-32-CHARS"
JWT_SECRET_KEY="CHANGE-THIS-TO-DIFFERENT-ULTRA-SECURE-JWT-SECRET-32-CHARS"
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7
JWT_ISSUER="your-production-api"
JWT_AUDIENCE="your-production-users"

# Production Cookie Security
REFRESH_TOKEN_COOKIE_DOMAIN=".yourdomain.com"
REFRESH_TOKEN_COOKIE_SECURE=true
REFRESH_TOKEN_COOKIE_SAMESITE="strict"

# Production Security Secrets
REFRESH_TOKEN_SECRET="ULTRA-SECURE-SEPARATE-SECRET-FOR-REFRESH-TOKENS"
SESSION_SECRET="ULTRA-SECURE-SESSION-SECRET-FOR-HMAC"
```

## Security Considerations

### Critical Security Requirements

1. **JWT Secret Keys**:
   - Must be at least 32 characters long
   - Should be cryptographically random
   - Different from general SECRET_KEY for defense in depth
   - Never commit to version control

2. **Refresh Token Security**:
   - 512-bit (64 bytes) cryptographically secure tokens
   - SHA512/HMAC for storage hashing
   - Automatic rotation on each use
   - Reuse detection with nuclear response (all sessions revoked)

3. **Cookie Security**:
   - HttpOnly flag (prevents XSS access)
   - Secure flag in production (HTTPS only)
   - SameSite=Strict (CSRF protection)
   - Proper domain configuration for production

### Production Hardening

```bash
# Additional Production Settings
JWT_ALGORITHM="RS256"  # Consider RSA256 for enhanced security
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15  # Shorter for high-security environments
JWT_REFRESH_TOKEN_EXPIRE_DAYS=1  # Shorter for maximum security

# Rate Limiting (handled by middleware)
JWT_REFRESH_RATE_LIMIT="10/minute"
JWT_LOGIN_RATE_LIMIT="5/minute"
```

## API Endpoints

### Authentication Endpoints

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `/api/v1/auth/login` | POST | Login with password, returns JWT + refresh cookie | No |
| `/api/v1/auth/token/refresh` | POST | Refresh access token using cookie | No (uses cookie) |
| `/api/v1/auth/logout` | POST | Logout current session | Yes (JWT) |
| `/api/v1/auth/logout/all` | POST | Logout all user sessions | Yes (JWT) |
| `/api/v1/auth/sessions` | GET | List active sessions | Yes (JWT) |

### Protected Route Usage

```python
from app.middleware.jwt_middleware import get_current_user, require_scopes, require_admin

# Basic JWT authentication
@router.get("/protected")
async def protected_endpoint(current_user: AuthenticatedUser = Depends(get_current_user)):
    return {"user_id": current_user.user_id}

# Scope-based authorization
@router.post("/admin-only")
async def admin_endpoint(current_user: AuthenticatedUser = Depends(require_admin())):
    return {"message": "Admin access granted"}

# Custom scope requirements
@router.put("/write-access")
async def write_endpoint(current_user: AuthenticatedUser = Depends(require_scopes("write"))):
    return {"message": "Write access granted"}
```

## Error Codes and Messages

### JWT Error Codes

| Error Code | HTTP Status | Turkish Message | Description |
|------------|-------------|-----------------|-------------|
| `ERR-TOKEN-INVALID` | 401 | Geçersiz token | General token validation failure |
| `ERR-TOKEN-EXPIRED` | 401 | Token süresi dolmuş | Access token has expired |
| `ERR-TOKEN-REVOKED` | 401 | Token iptal edilmiş | Session has been revoked |
| `ERR-TOKEN-MALFORMED` | 400 | Token formatı geçersiz | JWT format is invalid |
| `ERR-REFRESH-MISSING` | 401 | Refresh token bulunamadı | No refresh cookie provided |
| `ERR-REFRESH-INVALID` | 401 | Refresh token geçersiz | Invalid refresh token |
| `ERR-REFRESH-REUSE` | 401 | Token yeniden kullanım girişimi | Refresh token reuse detected |
| `ERR-SESSION-NOT-FOUND` | 401 | Oturum bulunamadı | Associated session not found |
| `ERR-INSUFFICIENT-SCOPES` | 403 | Yetersiz yetki | Missing required permissions |
| `ERR-ADMIN-REQUIRED` | 403 | Admin yetkisi gerekli | Admin role required |

## Security Features

### Token Security

- **Access Tokens**: JWT with 30-minute expiration
- **Refresh Tokens**: 512-bit opaque tokens with 7-day TTL
- **Session Correlation**: Every JWT contains session ID for validation
- **Automatic Rotation**: New refresh token on each use
- **Reuse Detection**: Immediate revocation of all user sessions on reuse

### Cookie Security

- **HttpOnly**: Prevents JavaScript access to refresh tokens
- **Secure**: HTTPS-only in production
- **SameSite=Strict**: Maximum CSRF protection
- **Domain Configuration**: Proper domain scoping for production
- **Path Restriction**: Limited to authentication paths

### Audit and Monitoring

- **Complete Audit Trail**: All token operations logged
- **Security Events**: Suspicious activities tracked
- **Device Fingerprinting**: Anomaly detection
- **Session Management**: Concurrent session limits
- **Performance Monitoring**: Token operation timing

## Troubleshooting

### Common Issues

1. **"Token süresi dolmuş" errors**:
   - Check system clock synchronization
   - Verify JWT_ACCESS_TOKEN_EXPIRE_MINUTES setting
   - Ensure refresh token rotation is working

2. **"Refresh token bulunamadı" errors**:
   - Verify cookie security settings
   - Check HTTPS configuration in production
   - Ensure proper domain configuration

3. **"Token yeniden kullanım girişimi" errors**:
   - This is expected security behavior
   - User needs to login again
   - Check for clock skew between servers

### Debug Mode

```bash
# Enable detailed JWT logging (development only)
LOG_LEVEL="DEBUG"
JWT_DEBUG_MODE=true
```

### Health Checks

```bash
# Verify JWT service health
curl -H "Authorization: Bearer <valid-token>" http://localhost:8000/api/v1/auth/sessions

# Check refresh token rotation
curl -X POST -b "rt=<refresh-token>" http://localhost:8000/api/v1/auth/token/refresh
```

## Migration from Legacy Auth

The new JWT system replaces the legacy auth.py implementation:

1. **Disable Legacy**: Legacy functions now return HTTP 501
2. **Update Imports**: Use new middleware instead of legacy auth
3. **Cookie Support**: Refresh tokens now use secure cookies
4. **Session Integration**: Full integration with Task 3.2 sessions

### Migration Steps

```python
# Old way (deprecated)
from app.auth import get_current_user, create_token_pair

# New way (Task 3.3)
from app.middleware.jwt_middleware import get_current_user, AuthenticatedUser
from app.services.token_service import token_service
from app.services.jwt_service import jwt_service
```

## Compliance and Standards

### Turkish KVKV Compliance

- Session data retention policies
- Audit logging for compliance
- Turkish error messages for users
- Data processing consent tracking

### Security Standards

- Banking-level token security
- Enterprise session management
- OWASP authentication guidelines
- Zero-trust security model

### Performance Requirements

- JWT verification < 50ms per request
- Token generation < 5ms per token
- Session lookup optimized with indexes
- Concurrent session support