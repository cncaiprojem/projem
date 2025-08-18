/**
 * Task 3.14: Ultra-Enterprise Auth Guard Provider
 * Complete integration of authentication, license checking, and idle timeout
 * with Turkish KVKV compliance and banking-grade security
 * 
 * This provider integrates:
 * - Route-based authentication guards
 * - License status monitoring
 * - Idle timeout management
 * - Turkish localized warnings
 * - KVKV compliant logging
 */

'use client'

import React, { createContext, useContext, useEffect, useState } from 'react'
import { usePathname } from 'next/navigation'
import { useAuth } from '@/hooks/useAuth'
import { useAuthGuard } from '@/hooks/useAuthGuard'
import { useIdleTimer } from '@/hooks/useIdleTimer'
import { authAPI } from '@/lib/auth-api'
import { LicenseBanner } from '@/components/ui/LicenseBanner'
import { IdleWarningModal } from '@/components/ui/IdleWarningModal'

// Context for accessing auth guard state throughout the app
interface AuthGuardContextType {
  isAuthenticated: boolean
  isLoading: boolean
  licenseStatus: any
  idleState: {
    isWarning: boolean
    remainingTime?: number
    isActive: boolean
  }
  refreshLicenseStatus: () => void
}

const AuthGuardContext = createContext<AuthGuardContextType | undefined>(undefined)

export function useAuthGuardContext() {
  const context = useContext(AuthGuardContext)
  if (!context) {
    throw new Error('useAuthGuardContext must be used within AuthGuardProvider')
  }
  return context
}

// Props for the provider
export interface AuthGuardProviderProps {
  children: React.ReactNode
  /** Whether to enable idle timeout (default: true) */
  enableIdleTimeout?: boolean
  /** Idle timeout in minutes (default: 30 for regular, 15 for banking) */
  idleTimeoutMinutes?: number
  /** Whether to use banking-grade settings (shorter timeouts) */
  bankingMode?: boolean
  /** Whether to show license banners (default: true) */
  showLicenseBanners?: boolean
  /** Custom idle timeout message */
  customIdleMessage?: string
}

export function AuthGuardProvider({
  children,
  enableIdleTimeout = true,
  idleTimeoutMinutes,
  bankingMode = false,
  showLicenseBanners = true,
  customIdleMessage
}: AuthGuardProviderProps) {
  const pathname = usePathname()
  const { isAuthenticated, isLoading: authLoading, logout } = useAuth()
  
  // License state
  const [licenseStatus, setLicenseStatus] = useState(null)
  const [licenseLoading, setLicenseLoading] = useState(false)
  
  // Auth guard state
  const { hasAccess, isLoading: guardLoading } = useAuthGuard({
    checkLicense: true,
    redirectOnFail: true
  })
  
  // Calculate idle timeout settings
  const idleConfig = {
    idleTime: (idleTimeoutMinutes || (bankingMode ? 15 : 30)) * 60 * 1000,
    warningTime: bankingMode ? 2 * 60 * 1000 : 5 * 60 * 1000, // 2min for banking, 5min for regular
    customWarningMessage: customIdleMessage
  }
  
  // Idle timer state
  const idleTimer = useIdleTimer({
    ...idleConfig,
    onBeforeLogout: async () => {
      // Log idle logout event (KVKV compliant - no PII)
      console.log('[AUTH-GUARD] Idle logout initiated', {
        timestamp: new Date().toISOString(),
        pathname,
        timeout_minutes: idleConfig.idleTime / 60000
      })
    }
  })
  
  // License status fetching
  const refreshLicenseStatus = async () => {
    if (!isAuthenticated) return
    
    setLicenseLoading(true)
    try {
      const status = await authAPI.getLicenseStatus()
      setLicenseStatus(status)
      
      // Log license check (KVKV compliant - no PII)
      console.log('[AUTH-GUARD] License status refreshed', {
        timestamp: new Date().toISOString(),
        status: status.status,
        days_remaining: status.days_remaining
      })
    } catch (error) {
      console.warn('Failed to fetch license status:', error)
      // Don't set error state - license issues are handled by auth guard
    } finally {
      setLicenseLoading(false)
    }
  }
  
  // Refresh license status when authentication changes
  useEffect(() => {
    if (isAuthenticated) {
      refreshLicenseStatus()
    } else {
      setLicenseStatus(null)
    }
  }, [isAuthenticated])
  
  // Periodic license status refresh (every 5 minutes)
  useEffect(() => {
    if (!isAuthenticated) return
    
    const interval = setInterval(refreshLicenseStatus, 5 * 60 * 1000)
    return () => clearInterval(interval)
  }, [isAuthenticated])
  
  // Handle idle timer warnings
  const handleIdleStayLoggedIn = () => {
    idleTimer.reset()
    
    // Log user activity (KVKV compliant)
    console.log('[AUTH-GUARD] User chose to stay logged in', {
      timestamp: new Date().toISOString(),
      pathname
    })
  }
  
  const handleIdleLogoutNow = async () => {
    // Log manual logout from idle warning (KVKV compliant)
    console.log('[AUTH-GUARD] User chose manual logout from idle warning', {
      timestamp: new Date().toISOString(),
      pathname
    })
    
    await logout()
  }
  
  // Context value
  const contextValue: AuthGuardContextType = {
    isAuthenticated,
    isLoading: authLoading || guardLoading || licenseLoading,
    licenseStatus,
    idleState: {
      isWarning: idleTimer.isWarning,
      remainingTime: idleTimer.remainingTime,
      isActive: idleTimer.isActive
    },
    refreshLicenseStatus
  }
  
  // Don't render children if authentication is loading
  if (authLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
          <p className="mt-2 text-gray-600">Kimlik doğrulanıyor...</p>
        </div>
      </div>
    )
  }
  
  return (
    <AuthGuardContext.Provider value={contextValue}>
      {/* Main content */}
      <div className="min-h-screen">
        {/* License Banner */}
        {showLicenseBanners && isAuthenticated && licenseStatus && (
          <LicenseBanner
            licenseStatus={licenseStatus}
            position="top"
            dismissible={licenseStatus.status !== 'expired' && licenseStatus.days_remaining > 1}
          />
        )}
        
        {/* Main app content */}
        {children}
      </div>
      
      {/* Idle Warning Modal */}
      {enableIdleTimeout && isAuthenticated && (
        <IdleWarningModal
          isVisible={idleTimer.isWarning}
          remainingTime={idleTimer.remainingTime}
          onStayLoggedIn={handleIdleStayLoggedIn}
          onLogoutNow={handleIdleLogoutNow}
          customMessage={customIdleMessage}
          showCountdown={true}
        />
      )}
    </AuthGuardContext.Provider>
  )
}

// HOC for protecting specific pages
export function withAuthGuard<P extends object>(
  Component: React.ComponentType<P>,
  options: {
    requiredRoles?: string[]
    minLicenseLevel?: string
    redirectTo?: string
  } = {}
) {
  const WrappedComponent = (props: P) => {
    const { hasAccess, isLoading, errorMessage } = useAuthGuard({
      requiredRoles: options.requiredRoles,
      minLicenseLevel: options.minLicenseLevel,
      redirectTo: options.redirectTo
    })
    
    if (isLoading) {
      return (
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-center">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto"></div>
            <p className="mt-2 text-gray-600">Yetki kontrol ediliyor...</p>
          </div>
        </div>
      )
    }
    
    if (!hasAccess) {
      return (
        <div className="min-h-screen flex items-center justify-center">
          <div className="text-center max-w-md">
            <div className="text-red-600 mb-4">
              <svg className="w-16 h-16 mx-auto" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
              </svg>
            </div>
            <h2 className="text-xl font-semibold text-gray-900 mb-2">
              Erişim Engellendi
            </h2>
            <p className="text-gray-600 mb-4">
              {errorMessage || 'Bu sayfaya erişim yetkiniz bulunmuyor.'}
            </p>
            <button
              onClick={() => window.history.back()}
              className="bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700"
            >
              Geri Dön
            </button>
          </div>
        </div>
      )
    }
    
    return <Component {...props} />
  }
  
  WrappedComponent.displayName = `withAuthGuard(${Component.displayName || Component.name})`
  
  return WrappedComponent
}

// Convenience HOCs for common scenarios
export function withAdminGuard<P extends object>(Component: React.ComponentType<P>) {
  return withAuthGuard(Component, {
    requiredRoles: ['admin', 'super_admin']
  })
}

export function withProfessionalLicense<P extends object>(Component: React.ComponentType<P>) {
  return withAuthGuard(Component, {
    minLicenseLevel: 'professional'
  })
}

export function withEnterpriseFeatures<P extends object>(Component: React.ComponentType<P>) {
  return withAuthGuard(Component, {
    minLicenseLevel: 'enterprise'
  })
}