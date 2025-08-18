/**
 * Task 3.14: Ultra-Enterprise Authentication Guard Hook
 * Client-side route protection with Turkish KVKV compliance
 * 
 * Features:
 * - Real-time authentication status monitoring
 * - Role-based access control (RBAC)
 * - License status integration
 * - Turkish error messages
 * - Automatic redirects on unauthorized access
 * - KVKV compliant client-side logging
 */

import { useEffect, useState, useCallback, useMemo } from 'react'
import { useRouter, usePathname } from 'next/navigation'
import { useAuth } from './useAuth'

// Types for auth guard configuration
export interface AuthGuardConfig {
  /** Required roles to access the protected resource */
  requiredRoles?: string[]
  /** Whether to redirect on auth failure (default: true) */
  redirectOnFail?: boolean
  /** Custom redirect path (default: /login) */
  redirectTo?: string
  /** Whether to check license status (default: true) */
  checkLicense?: boolean
  /** Minimum license status required ('trial', 'basic', 'professional', 'enterprise') */
  minLicenseLevel?: string
  /** Whether to show loading state during checks (default: true) */
  showLoading?: boolean
}

export interface AuthGuardResult {
  /** Whether the user has access to the resource */
  hasAccess: boolean
  /** Whether the auth check is still loading */
  isLoading: boolean
  /** Current user's role if authenticated */
  userRole?: string
  /** License status information */
  licenseStatus?: {
    status: string
    daysRemaining: number
    warningMessage?: string
  }
  /** Error message in Turkish if access denied */
  errorMessage?: string
  /** Function to manually recheck access */
  recheckAccess: () => void
}

// Default configuration
const DEFAULT_CONFIG: Required<AuthGuardConfig> = {
  requiredRoles: [],
  redirectOnFail: true,
  redirectTo: '/login',
  checkLicense: true,
  minLicenseLevel: 'trial',
  showLoading: true
}

// Role hierarchy for license level checking
const LICENSE_HIERARCHY = {
  'trial': 0,
  'basic': 1,
  'professional': 2,
  'enterprise': 3
}

// Helper function to check if user has required role
function hasRequiredRole(userRole: string, requiredRoles: string[]): boolean {
  if (requiredRoles.length === 0) return true
  return requiredRoles.includes(userRole)
}

// Helper function to check license level
function hasRequiredLicense(userLicenseLevel: string, minLicenseLevel: string): boolean {
  const userLevel = LICENSE_HIERARCHY[userLicenseLevel as keyof typeof LICENSE_HIERARCHY] ?? -1
  const requiredLevel = LICENSE_HIERARCHY[minLicenseLevel as keyof typeof LICENSE_HIERARCHY] ?? 999
  return userLevel >= requiredLevel
}

// Client-side logging function (KVKV compliant - no PII)
function logAccessEvent(
  event: 'access_granted' | 'access_denied' | 'redirect_triggered',
  details: {
    pathname?: string
    reason?: string
    requiredRoles?: string[]
    userRole?: string
    licenseStatus?: string
  }
): void {
  // Only log in development or when explicitly enabled
  if (process.env.NODE_ENV === 'development' || process.env.NEXT_PUBLIC_ENABLE_CLIENT_AUDIT === 'true') {
    const logEntry = {
      timestamp: new Date().toISOString(),
      event,
      ...details
    }
    console.log('[AUTH-GUARD]', logEntry)
  }
  
  // In production, this would send to analytics/monitoring
  // without any PII data, complying with Turkish KVKV requirements
}

export function useAuthGuard(config: AuthGuardConfig = {}): AuthGuardResult {
  const router = useRouter()
  const pathname = usePathname()
  const { isAuthenticated, user, isLoading: authLoading, sessionInfo } = useAuth()
  
  const [isChecking, setIsChecking] = useState(true)
  const [licenseStatus, setLicenseStatus] = useState<AuthGuardResult['licenseStatus']>()
  const [errorMessage, setErrorMessage] = useState<string>()
  
  // Merge config with defaults
  const finalConfig = useMemo(
    () => ({ ...DEFAULT_CONFIG, ...config }),
    [config]
  )
  
  // Check access permissions
  const checkAccess = useCallback(async () => {
    if (!finalConfig.showLoading && authLoading) {
      return
    }
    
    setIsChecking(true)
    setErrorMessage(undefined)
    
    try {
      // Step 1: Check authentication
      if (!isAuthenticated || !user) {
        logAccessEvent('access_denied', {
          pathname,
          reason: 'not_authenticated',
          requiredRoles: finalConfig.requiredRoles
        })
        
        setErrorMessage('Oturum açmanız gerekiyor')
        
        if (finalConfig.redirectOnFail) {
          const redirectUrl = new URL(finalConfig.redirectTo, window.location.origin)
          redirectUrl.searchParams.set('returnUrl', pathname)
          redirectUrl.searchParams.set('message_tr', 'Oturum açmanız gerekiyor')
          
          logAccessEvent('redirect_triggered', {
            pathname,
            reason: 'not_authenticated'
          })
          
          router.push(redirectUrl.toString())
        }
        
        return false
      }
      
      // Step 2: Check role-based access
      const userRole = user.role || 'user'
      const hasRoleAccess = hasRequiredRole(userRole, finalConfig.requiredRoles)
      
      if (!hasRoleAccess) {
        logAccessEvent('access_denied', {
          pathname,
          reason: 'insufficient_role',
          requiredRoles: finalConfig.requiredRoles,
          userRole
        })
        
        setErrorMessage(`Bu sayfaya erişim yetkiniz yok. Gerekli rol: ${finalConfig.requiredRoles.join(', ')}`)
        
        if (finalConfig.redirectOnFail) {
          const redirectUrl = new URL('/', window.location.origin)
          redirectUrl.searchParams.set('message_tr', 'Bu sayfaya erişim yetkiniz yok')
          
          logAccessEvent('redirect_triggered', {
            pathname,
            reason: 'insufficient_role',
            userRole,
            requiredRoles: finalConfig.requiredRoles
          })
          
          router.push(redirectUrl.toString())
        }
        
        return false
      }
      
      // Step 3: Check license status if required
      if (finalConfig.checkLicense) {
        try {
          const response = await fetch('/api/v1/license/me', {
            method: 'GET',
            credentials: 'include',
            cache: 'no-store'
          })
          
          if (response.ok) {
            const licenseData = await response.json()
            
            setLicenseStatus({
              status: licenseData.status,
              daysRemaining: licenseData.days_remaining,
              warningMessage: licenseData.warning_message_tr
            })
            
            // Check if license meets minimum level requirement
            const hasLicenseAccess = hasRequiredLicense(licenseData.status, finalConfig.minLicenseLevel)
            
            if (!hasLicenseAccess) {
              logAccessEvent('access_denied', {
                pathname,
                reason: 'insufficient_license',
                licenseStatus: licenseData.status
              })
              
              setErrorMessage(`Bu özellik için ${finalConfig.minLicenseLevel} veya üzeri lisans gerekiyor`)
              
              if (finalConfig.redirectOnFail) {
                const redirectUrl = new URL('/license', window.location.origin)
                redirectUrl.searchParams.set('message_tr', 'Lisans yükseltmesi gerekiyor')
                redirectUrl.searchParams.set('required_level', finalConfig.minLicenseLevel)
                
                logAccessEvent('redirect_triggered', {
                  pathname,
                  reason: 'insufficient_license'
                })
                
                router.push(redirectUrl.toString())
              }
              
              return false
            }
            
            // Handle expired license
            if (licenseData.status === 'expired') {
              logAccessEvent('access_denied', {
                pathname,
                reason: 'license_expired'
              })
              
              setErrorMessage('Lisansınızın süresi dolmuş')
              
              if (finalConfig.redirectOnFail) {
                const redirectUrl = new URL('/license', window.location.origin)
                redirectUrl.searchParams.set('status', 'expired')
                redirectUrl.searchParams.set('message_tr', 'Lisansınızın süresi dolmuş')
                
                logAccessEvent('redirect_triggered', {
                  pathname,
                  reason: 'license_expired'
                })
                
                router.push(redirectUrl.toString())
              }
              
              return false
            }
          } else if (response.status === 404) {
            // No license found - might need setup
            setLicenseStatus({
              status: 'none',
              daysRemaining: 0,
              warningMessage: 'Lisans bulunamadı'
            })
            
            logAccessEvent('access_denied', {
              pathname,
              reason: 'no_license'
            })
            
            setErrorMessage('Lisans bulunamadı')
            
            if (finalConfig.redirectOnFail) {
              const redirectUrl = new URL('/license', window.location.origin)
              redirectUrl.searchParams.set('message_tr', 'Lisans kurulumu gerekiyor')
              
              logAccessEvent('redirect_triggered', {
                pathname,
                reason: 'no_license'
              })
              
              router.push(redirectUrl.toString())
            }
            
            return false
          }
        } catch (error) {
          // License check failed - log but don't block access
          console.warn('License check failed:', error)
          
          // Set default license status
          setLicenseStatus({
            status: 'unknown',
            daysRemaining: 0,
            warningMessage: 'Lisans durumu kontrol edilemiyor'
          })
        }
      }
      
      // All checks passed
      logAccessEvent('access_granted', {
        pathname,
        userRole,
        licenseStatus: licenseStatus?.status
      })
      
      return true
      
    } catch (error) {
      console.error('Auth guard check failed:', error)
      setErrorMessage('Yetkilendirme kontrolü başarısız oldu')
      return false
    } finally {
      setIsChecking(false)
    }
  }, [
    isAuthenticated,
    user,
    pathname,
    finalConfig,
    authLoading,
    router,
    licenseStatus?.status
  ])
  
  // Run access check when dependencies change
  useEffect(() => {
    if (!authLoading) {
      checkAccess()
    }
  }, [checkAccess, authLoading])
  
  // Determine final access state
  const hasAccess = useMemo(() => {
    if (authLoading || isChecking) return false
    if (!isAuthenticated || !user) return false
    if (errorMessage) return false
    return true
  }, [authLoading, isChecking, isAuthenticated, user, errorMessage])
  
  // Determine loading state
  const isLoading = useMemo(() => {
    if (!finalConfig.showLoading) return false
    return authLoading || isChecking
  }, [authLoading, isChecking, finalConfig.showLoading])
  
  return {
    hasAccess,
    isLoading,
    userRole: user?.role,
    licenseStatus,
    errorMessage,
    recheckAccess: checkAccess
  }
}

// Convenience hooks for common scenarios
export function useAdminGuard(config: Omit<AuthGuardConfig, 'requiredRoles'> = {}): AuthGuardResult {
  return useAuthGuard({
    ...config,
    requiredRoles: ['admin', 'super_admin']
  })
}

export function useRoleGuard(
  roles: string[], 
  config: Omit<AuthGuardConfig, 'requiredRoles'> = {}
): AuthGuardResult {
  return useAuthGuard({
    ...config,
    requiredRoles: roles
  })
}

export function useLicenseGuard(
  minLicenseLevel: string,
  config: Omit<AuthGuardConfig, 'minLicenseLevel'> = {}
): AuthGuardResult {
  return useAuthGuard({
    ...config,
    minLicenseLevel,
    checkLicense: true
  })
}