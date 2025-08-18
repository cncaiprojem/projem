# Task 3.14: Frontend Route Guards and Idle Logout - Integration Guide

## Overview

Task 3.14 implements ultra-enterprise banking-grade authentication guards with Turkish KVKV compliance, including:

- **Next.js Middleware**: Server-side route protection with JWT validation and license checking
- **Client-Side Guards**: React hooks for real-time auth and license validation
- **Idle Timer System**: Automatic logout with configurable timeouts and warnings
- **Turkish Localization**: Complete Turkish language support with KVKV compliance
- **License Management**: Real-time license status monitoring with expiry warnings

## Files Created

### Backend (API)
- `apps/api/app/routers/license.py` - License management endpoints
- Updated `apps/api/app/main.py` - Added license router

### Frontend (Web)
- `apps/web/src/middleware.ts` - Next.js middleware for route protection
- `apps/web/src/hooks/useAuthGuard.ts` - Client-side auth protection hook
- `apps/web/src/hooks/useIdleTimer.ts` - Idle timeout management hook
- `apps/web/src/components/ui/LicenseBanner.tsx` - License status banner component
- `apps/web/src/components/ui/IdleWarningModal.tsx` - Idle timeout warning modal
- `apps/web/src/components/auth/AuthGuardProvider.tsx` - Complete integration provider
- Updated `apps/web/src/lib/auth-api.ts` - Added license API methods and Turkish errors
- Updated `apps/web/src/lib/i18n/locales/tr.json` - Added Turkish localization

## Integration Examples

### 1. Basic Setup in Root Layout

```typescript
// apps/web/src/app/layout.tsx
import { AuthGuardProvider } from '@/components/auth/AuthGuardProvider'

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="tr">
      <body>
        <AuthGuardProvider
          enableIdleTimeout={true}
          idleTimeoutMinutes={30}
          showLicenseBanners={true}
          bankingMode={false} // Set to true for banking-grade security
        >
          {children}
        </AuthGuardProvider>
      </body>
    </html>
  )
}
```

### 2. Banking-Grade Security Setup

```typescript
// For ultra-secure applications (banking, financial)
<AuthGuardProvider
  enableIdleTimeout={true}
  idleTimeoutMinutes={15} // Shorter timeout
  bankingMode={true}
  showLicenseBanners={true}
  customIdleMessage="Bankacılık seviyesinde güvenlik protokolü nedeniyle oturumunuz kısa sürede sonlandırılacak."
>
  {children}
</AuthGuardProvider>
```

### 3. Protected Page with Role Requirements

```typescript
// apps/web/src/app/admin/page.tsx
import { withAdminGuard } from '@/components/auth/AuthGuardProvider'

function AdminDashboard() {
  return (
    <div>
      <h1>Admin Dashboard</h1>
      <p>Only admins can see this content</p>
    </div>
  )
}

export default withAdminGuard(AdminDashboard)
```

### 4. Protected Page with License Requirements

```typescript
// apps/web/src/app/professional-features/page.tsx
import { withProfessionalLicense } from '@/components/auth/AuthGuardProvider'

function ProfessionalFeatures() {
  return (
    <div>
      <h1>Professional Features</h1>
      <p>Requires Professional or Enterprise license</p>
    </div>
  )
}

export default withProfessionalLicense(ProfessionalFeatures)
```

### 5. Manual Auth Guard Usage

```typescript
// Manual usage in any component
import { useAuthGuard } from '@/hooks/useAuthGuard'
import { useLicenseStatus } from '@/hooks/useLicenseStatus'

function MyProtectedComponent() {
  const { hasAccess, isLoading, errorMessage, licenseStatus } = useAuthGuard({
    requiredRoles: ['user'],
    minLicenseLevel: 'basic',
    checkLicense: true
  })

  if (isLoading) {
    return <div>Yetki kontrol ediliyor...</div>
  }

  if (!hasAccess) {
    return <div>Erişim reddedildi: {errorMessage}</div>
  }

  return (
    <div>
      <h1>Protected Content</h1>
      {licenseStatus && (
        <p>License Status: {licenseStatus.status_tr}</p>
      )}
    </div>
  )
}
```

### 6. Idle Timer Customization

```typescript
import { useIdleTimer } from '@/hooks/useIdleTimer'

function MyComponent() {
  const idleTimer = useIdleTimer({
    idleTime: 20 * 60 * 1000, // 20 minutes
    warningTime: 3 * 60 * 1000, // 3 minutes warning
    showCountdown: true,
    onBeforeLogout: async () => {
      // Save user data before logout
      await saveUserData()
    }
  })

  return (
    <div>
      {idleTimer.isWarning && (
        <div className="warning">
          Oturum {idleTimer.remainingTime} saniye içinde sonlanacak!
        </div>
      )}
    </div>
  )
}
```

## API Endpoints

### License Status Check
```bash
GET /api/v1/license/me
```

Response:
```json
{
  "status": "active",
  "days_remaining": 15,
  "expires_at": "2024-09-01T00:00:00Z",
  "plan_type": "professional",
  "seats_total": 5,
  "seats_used": 2,
  "features": {
    "cad_advanced": true,
    "cam_advanced": true,
    "max_jobs": 1000
  },
  "auto_renew": true,
  "status_tr": "aktif",
  "warning_message_tr": "Lisansınızın süresi 15 gün içinde dolacak.",
  "renewal_url": "/license/renew"
}
```

### Feature Availability Check
```bash
POST /api/v1/license/check-feature
Content-Type: application/json

{
  "feature": "cad_advanced"
}
```

Response:
```json
{
  "feature": "cad_advanced",
  "available": true,
  "limit": null,
  "current_usage": null
}
```

## Security Features

### 1. KVKV Compliance
- All logging excludes personally identifiable information (PII)
- Turkish privacy law compliance
- Secure data handling throughout the system

### 2. Ultra-Enterprise Security
- Banking-grade session management
- JWT token validation in middleware
- Automatic license status monitoring
- Cross-tab idle timer synchronization
- Secure token storage (memory only, no localStorage)

### 3. Turkish Localization
- Complete Turkish language support
- Culturally appropriate error messages
- Turkish date/time formatting
- KVKV-compliant privacy notices

## Configuration Options

### Environment Variables

```bash
# Frontend (.env.local)
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_ENABLE_CLIENT_AUDIT=false
NEXT_PUBLIC_DEV_AUTH_BYPASS=false

# Backend (.env)
DEV_AUTH_BYPASS=true  # Only in development
SECRET_KEY=your-ultra-secure-secret-key
```

### Middleware Configuration

The middleware automatically protects all routes except:
- `/` (home page)
- `/login`
- `/register`
- `/auth/*` (authentication pages)
- `/healthz`
- `/help`

### Idle Timer Defaults

- **Regular Mode**: 30 minutes idle, 5 minutes warning
- **Banking Mode**: 15 minutes idle, 2 minutes warning
- **Development Mode**: 60 minutes idle, 5 minutes warning

## Testing

### Manual Testing Checklist

1. **Middleware Protection**:
   - [ ] Unauthenticated users redirected to login
   - [ ] Invalid JWT tokens cleared and redirected
   - [ ] Expired licenses redirect to license page
   - [ ] Admin routes block non-admin users

2. **Idle Timer**:
   - [ ] Warning appears before timeout
   - [ ] Countdown displays correctly
   - [ ] "Stay logged in" extends session
   - [ ] Auto-logout clears session completely
   - [ ] Cross-tab synchronization works

3. **License Banners**:
   - [ ] Expired licenses show critical banner
   - [ ] Expiring licenses show warning with countdown
   - [ ] Trial licenses show appropriate messages
   - [ ] Banners dismissible when appropriate

4. **Turkish Localization**:
   - [ ] All error messages in Turkish
   - [ ] Date/time formatting correct
   - [ ] License status translations accurate
   - [ ] Idle timer messages in Turkish

## Troubleshooting

### Common Issues

1. **Middleware not running**: Check `next.config.js` matcher configuration
2. **License check fails**: Verify API endpoints are accessible
3. **Idle timer not working**: Ensure `AuthGuardProvider` wraps the app
4. **Turkish text not displaying**: Check browser language settings

### Debug Logging

Enable debug logging by setting:
```bash
NEXT_PUBLIC_ENABLE_CLIENT_AUDIT=true
```

This will log KVKV-compliant security events to the browser console.

## Performance Considerations

- License status cached for 5 minutes
- Idle timer uses throttled activity detection
- Cross-tab sync uses efficient localStorage events
- Middleware optimized for minimal latency

## Security Audit Notes

This implementation meets ultra-enterprise banking standards:
- No PII in logs (KVKV compliant)
- Secure token handling
- Comprehensive session management
- Real-time license validation
- Multi-layer protection (middleware + client guards)
- Turkish regulatory compliance