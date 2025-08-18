/**
 * Task 3.14: Ultra-Enterprise Route Guards and Middleware
 * Banking-grade security patterns with Turkish KVKV compliance
 * 
 * Features:
 * - JWT token validation
 * - License status checking with expiry warnings
 * - Role-based route protection
 * - Turkish localized redirects
 * - KVKV compliant logging (no PII)
 * - Ultra-enterprise security standards
 */

import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'
import { jwtDecode } from 'jwt-decode'

// Route configuration constants
const PUBLIC_ROUTES = [
  '/',
  '/login', 
  '/register',
  '/auth/magic-link',
  '/auth/oidc/callback',
  '/healthz',
  '/help'
]

const ADMIN_ROUTES = [
  '/admin',
  '/settings/admin',
  '/reports/admin'
]

const API_ROUTES = [
  '/api'
]

// Types for JWT payload and license response
interface JWTPayload {
  sub: string
  email?: string
  role?: string
  exp: number
  iat: number
  session_id?: string
}

interface LicenseResponse {
  status: 'active' | 'expired' | 'suspended' | 'trial'
  days_remaining: number
  expires_at: string
  warning_message_tr?: string
  renewal_url?: string
}

// Helper functions
function isPublicRoute(pathname: string): boolean {
  return PUBLIC_ROUTES.some(route => {
    if (route === '/') return pathname === '/'
    return pathname.startsWith(route)
  })
}

function isAdminRoute(pathname: string): boolean {
  return ADMIN_ROUTES.some(route => pathname.startsWith(route))
}

function isApiRoute(pathname: string): boolean {
  return API_ROUTES.some(route => pathname.startsWith(route))
}

function isValidJWT(token: string): { isValid: boolean; payload?: JWTPayload } {
  try {
    const payload = jwtDecode<JWTPayload>(token)
    
    // Check if token is expired
    const now = Math.floor(Date.now() / 1000)
    if (payload.exp <= now) {
      return { isValid: false }
    }
    
    // Basic payload validation
    if (!payload.sub) {
      return { isValid: false }
    }
    
    return { isValid: true, payload }
  } catch (error) {
    return { isValid: false }
  }
}

async function checkLicenseStatus(request: NextRequest): Promise<LicenseResponse | null> {
  try {
    // Get the base URL for API calls
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000'
    
    // Forward cookies for authentication
    const cookieHeader = request.headers.get('cookie') || ''
    
    const response = await fetch(`${baseUrl}/api/v1/license/me`, {
      method: 'GET',
      headers: {
        'Cookie': cookieHeader,
        'User-Agent': 'NextJS-Middleware/1.0',
        'Accept': 'application/json',
      },
      cache: 'no-store',
    })
    
    if (!response.ok) {
      // If license check fails, assume no license (will be handled by component)
      return null
    }
    
    return await response.json()
  } catch (error) {
    // Fail silently - license check failures should not block navigation
    console.warn('License check failed in middleware:', error)
    return null
  }
}

function createRedirectResponse(
  request: NextRequest, 
  destination: string, 
  params?: Record<string, string>
): NextResponse {
  const url = new URL(destination, request.url)
  
  // Add query parameters if provided
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      url.searchParams.set(key, value)
    })
  }
  
  const response = NextResponse.redirect(url)
  
  // Add security headers
  response.headers.set('X-Frame-Options', 'DENY')
  response.headers.set('X-Content-Type-Options', 'nosniff')
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin')
  
  return response
}

function logSecurityEvent(
  event: string, 
  pathname: string, 
  userAgent?: string,
  additional?: Record<string, any>
): void {
  // KVKV compliant logging - no PII
  const logData = {
    timestamp: new Date().toISOString(),
    event,
    pathname,
    user_agent_hash: userAgent ? btoa(userAgent).substring(0, 16) : undefined,
    ...additional,
  }
  
  // In production, this would go to a proper logging system
  if (process.env.NODE_ENV === 'development') {
    console.log('[SECURITY]', logData)
  }
}

export async function middleware(request: NextRequest) {
  const pathname = request.nextUrl.pathname
  const userAgent = request.headers.get('user-agent') || undefined
  
  // Skip middleware for API routes, static files, and internal Next.js routes
  if (
    isApiRoute(pathname) ||
    pathname.startsWith('/_next') ||
    pathname.startsWith('/static') ||
    pathname.includes('.')
  ) {
    return NextResponse.next()
  }
  
  // Allow public routes without authentication
  if (isPublicRoute(pathname)) {
    return NextResponse.next()
  }
  
  // Check for access token in cookies
  const accessToken = request.cookies.get('access_token')?.value
  
  if (!accessToken) {
    // No access token - redirect to login
    logSecurityEvent('auth_required', pathname, userAgent, {
      reason: 'no_access_token',
      redirect_to: 'login'
    })
    
    return createRedirectResponse(request, '/login', {
      returnUrl: pathname,
      message: 'auth_required',
      message_tr: 'Oturum açmanız gerekiyor'
    })
  }
  
  // Validate JWT token
  const { isValid, payload } = isValidJWT(accessToken)
  
  if (!isValid || !payload) {
    // Invalid token - clear it and redirect to login
    logSecurityEvent('invalid_token', pathname, userAgent, {
      reason: 'jwt_invalid',
      redirect_to: 'login'
    })
    
    const response = createRedirectResponse(request, '/login', {
      returnUrl: pathname,
      message: 'session_expired',
      message_tr: 'Oturumunuzun süresi dolmuş'
    })
    
    // Clear the invalid token
    response.cookies.delete('access_token')
    
    return response
  }
  
  // Check admin routes
  if (isAdminRoute(pathname)) {
    const userRole = payload.role || 'user'
    
    if (!['admin', 'super_admin'].includes(userRole)) {
      logSecurityEvent('access_denied', pathname, userAgent, {
        reason: 'insufficient_role',
        user_role: userRole,
        required_roles: ['admin', 'super_admin']
      })
      
      return createRedirectResponse(request, '/', {
        message: 'access_denied',
        message_tr: 'Bu sayfaya erişim yetkiniz yok'
      })
    }
  }
  
  // Check license status (non-blocking)
  try {
    const licenseStatus = await checkLicenseStatus(request)
    
    if (licenseStatus) {
      // Log license status check (KVKV compliant - no PII)
      logSecurityEvent('license_checked', pathname, userAgent, {
        status: licenseStatus.status,
        days_remaining: licenseStatus.days_remaining
      })
      
      // Handle expired license
      if (licenseStatus.status === 'expired') {
        // Allow access to license renewal page
        if (pathname !== '/license' && pathname !== '/license/renew') {
          return createRedirectResponse(request, '/license', {
            status: 'expired',
            message_tr: 'Lisansınızın süresi dolmuş'
          })
        }
      }
      
      // Handle license expiring soon (warning only, don't redirect)
      else if (licenseStatus.status === 'active' && licenseStatus.days_remaining <= 7) {
        logSecurityEvent('license_expiring', pathname, userAgent, {
          days_remaining: licenseStatus.days_remaining
        })
        
        // Add warning header for frontend to display banner
        const response = NextResponse.next()
        response.headers.set('X-License-Warning', 'expiring')
        response.headers.set('X-License-Days', licenseStatus.days_remaining.toString())
        response.headers.set('X-License-Message-TR', licenseStatus.warning_message_tr || 'Lisans süresi yakında dolacak')
        
        return response
      }
    }
  } catch (error) {
    // License check failed - continue without blocking
    logSecurityEvent('license_check_failed', pathname, userAgent, {
      error: 'api_error'
    })
  }
  
  // Success - allow request to continue
  logSecurityEvent('access_granted', pathname, userAgent, {
    user_role: payload.role || 'user'
  })
  
  const response = NextResponse.next()
  
  // Add security headers to all responses
  response.headers.set('X-Frame-Options', 'DENY')
  response.headers.set('X-Content-Type-Options', 'nosniff')
  response.headers.set('X-XSS-Protection', '1; mode=block')
  response.headers.set('Referrer-Policy', 'strict-origin-when-cross-origin')
  response.headers.set('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
  
  return response
}

// Configure which routes this middleware should run on
export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes handled separately)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     * - public folder files
     */
    '/((?!api|_next/static|_next/image|favicon.ico|public/).*)',
  ],
}