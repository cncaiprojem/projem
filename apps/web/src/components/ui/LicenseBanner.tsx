/**
 * Task 3.14: Ultra-Enterprise License Banner Component
 * Turkish localized license status and warning notifications
 * 
 * Features:
 * - Real-time license status display
 * - Expiry warnings with countdown
 * - Turkish KVKV compliance
 * - Banking-grade visual design
 * - Accessibility support
 * - Multiple severity levels
 * - Auto-dismissible warnings
 */

'use client'

import React, { useState, useEffect, useMemo } from 'react'
import { X, AlertTriangle, Info, Clock, CreditCard, CheckCircle } from 'lucide-react'
import { Button } from './Button'

// License status interface
export interface LicenseStatus {
  status: 'active' | 'expired' | 'suspended' | 'trial' | 'none'
  daysRemaining: number
  expiresAt: string
  planType?: string
  warningMessage?: string
  renewalUrl?: string
}

// Component props
export interface LicenseBannerProps {
  /** License status data */
  licenseStatus: LicenseStatus | null
  /** Whether to show the banner (controlled) */
  isVisible?: boolean
  /** Callback when banner is dismissed */
  onDismiss?: () => void
  /** Whether the banner can be dismissed */
  dismissible?: boolean
  /** Custom className for styling */
  className?: string
  /** Position of the banner */
  position?: 'top' | 'bottom'
  /** Whether to show countdown timer */
  showCountdown?: boolean
  /** Custom action button text */
  actionText?: string
  /** Custom action button callback */
  onAction?: () => void
}

// Helper function to determine banner severity and styling
function getBannerConfig(status: LicenseStatus['status'], daysRemaining: number) {
  switch (status) {
    case 'expired':
      return {
        severity: 'error' as const,
        icon: AlertTriangle,
        bgColor: 'bg-red-50 border-red-200',
        textColor: 'text-red-800',
        iconColor: 'text-red-500',
        buttonColor: 'bg-red-600 hover:bg-red-700 text-white',
        title: 'Lisans Süresi Dolmuş',
        defaultMessage: 'Lisansınızın süresi dolmuş. Hizmetlere erişim kısıtlanabilir.'
      }
    case 'suspended':
      return {
        severity: 'error' as const,
        icon: AlertTriangle,
        bgColor: 'bg-red-50 border-red-200',
        textColor: 'text-red-800',
        iconColor: 'text-red-500',
        buttonColor: 'bg-red-600 hover:bg-red-700 text-white',
        title: 'Lisans Askıya Alınmış',
        defaultMessage: 'Lisansınız askıya alınmış. Lütfen yönetici ile iletişime geçin.'
      }
    case 'trial':
      if (daysRemaining <= 3) {
        return {
          severity: 'warning' as const,
          icon: Clock,
          bgColor: 'bg-amber-50 border-amber-200',
          textColor: 'text-amber-800',
          iconColor: 'text-amber-500',
          buttonColor: 'bg-amber-600 hover:bg-amber-700 text-white',
          title: 'Deneme Süresi Bitiyor',
          defaultMessage: `Deneme süreniz ${daysRemaining} gün içinde dolacak!`
        }
      } else {
        return {
          severity: 'info' as const,
          icon: Info,
          bgColor: 'bg-blue-50 border-blue-200',
          textColor: 'text-blue-800',
          iconColor: 'text-blue-500',
          buttonColor: 'bg-blue-600 hover:bg-blue-700 text-white',
          title: 'Deneme Lisansı',
          defaultMessage: `Deneme süreniz ${daysRemaining} gün içinde dolacak.`
        }
      }
    case 'active':
      if (daysRemaining <= 3) {
        return {
          severity: 'error' as const,
          icon: AlertTriangle,
          bgColor: 'bg-red-50 border-red-200',
          textColor: 'text-red-800',
          iconColor: 'text-red-500',
          buttonColor: 'bg-red-600 hover:bg-red-700 text-white',
          title: 'Acil: Lisans Yenilenmesi',
          defaultMessage: `Lisansınızın süresi ${daysRemaining} gün içinde dolacak!`
        }
      } else if (daysRemaining <= 7) {
        return {
          severity: 'warning' as const,
          icon: Clock,
          bgColor: 'bg-amber-50 border-amber-200',
          textColor: 'text-amber-800',
          iconColor: 'text-amber-500',
          buttonColor: 'bg-amber-600 hover:bg-amber-700 text-white',
          title: 'Lisans Yenilenmesi',
          defaultMessage: `Lisansınızın süresi ${daysRemaining} gün içinde dolacak.`
        }
      } else if (daysRemaining <= 30) {
        return {
          severity: 'info' as const,
          icon: Info,
          bgColor: 'bg-blue-50 border-blue-200',
          textColor: 'text-blue-800',
          iconColor: 'text-blue-500',
          buttonColor: 'bg-blue-600 hover:bg-blue-700 text-white',
          title: 'Lisans Yenileme Hatırlatması',
          defaultMessage: `Lisansınızın süresi ${daysRemaining} gün içinde dolacak.`
        }
      } else {
        return null // No banner needed for active licenses with >30 days
      }
    case 'none':
      return {
        severity: 'error' as const,
        icon: CreditCard,
        bgColor: 'bg-red-50 border-red-200',
        textColor: 'text-red-800',
        iconColor: 'text-red-500',
        buttonColor: 'bg-red-600 hover:bg-red-700 text-white',
        title: 'Lisans Gerekiyor',
        defaultMessage: 'Hizmetleri kullanabilmek için bir lisans planı seçmelisiniz.'
      }
    default:
      return null
  }
}

// Countdown component for time-sensitive warnings
function CountdownTimer({ expiresAt, showDays = true }: { expiresAt: string, showDays?: boolean }) {
  const [timeLeft, setTimeLeft] = useState<string>('')
  
  useEffect(() => {
    const updateCountdown = () => {
      const now = new Date().getTime()
      const expiry = new Date(expiresAt).getTime()
      const distance = expiry - now
      
      if (distance > 0) {
        const days = Math.floor(distance / (1000 * 60 * 60 * 24))
        const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60))
        const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60))
        
        if (showDays && days > 0) {
          setTimeLeft(`${days} gün ${hours} saat`)
        } else if (hours > 0) {
          setTimeLeft(`${hours} saat ${minutes} dakika`)
        } else {
          setTimeLeft(`${minutes} dakika`)
        }
      } else {
        setTimeLeft('Süresi dolmuş')
      }
    }
    
    updateCountdown()
    const interval = setInterval(updateCountdown, 60000) // Update every minute
    
    return () => clearInterval(interval)
  }, [expiresAt, showDays])
  
  return <span className="font-mono text-sm">{timeLeft}</span>
}

export function LicenseBanner({
  licenseStatus,
  isVisible = true,
  onDismiss,
  dismissible = true,
  className = '',
  position = 'top',
  showCountdown = true,
  actionText,
  onAction
}: LicenseBannerProps) {
  const [isDismissed, setIsDismissed] = useState(false)
  
  // Calculate banner configuration
  const bannerConfig = useMemo(() => {
    if (!licenseStatus) return null
    return getBannerConfig(licenseStatus.status, licenseStatus.daysRemaining)
  }, [licenseStatus])
  
  // Don't render if no license data, dismissed, not visible, or no config
  if (!licenseStatus || isDismissed || !isVisible || !bannerConfig) {
    return null
  }
  
  const handleDismiss = () => {
    setIsDismissed(true)
    onDismiss?.()
  }
  
  const handleAction = () => {
    if (onAction) {
      onAction()
    } else if (licenseStatus.renewalUrl) {
      window.location.href = licenseStatus.renewalUrl
    } else {
      // Default action: go to license page
      window.location.href = '/license'
    }
  }
  
  const IconComponent = bannerConfig.icon
  const message = licenseStatus.warningMessage || bannerConfig.defaultMessage
  
  // Determine if this is a critical banner that shouldn't be dismissible
  const isCritical = bannerConfig.severity === 'error' && 
    (licenseStatus.status === 'expired' || licenseStatus.status === 'none')
  
  const canDismiss = dismissible && !isCritical
  
  return (
    <div
      className={`
        relative border-l-4 border-r border-t border-b rounded-r-lg shadow-sm
        ${bannerConfig.bgColor}
        ${position === 'top' ? 'mb-4' : 'mt-4'}
        ${className}
      `}
      role="alert"
      aria-live={bannerConfig.severity === 'error' ? 'assertive' : 'polite'}
      aria-label={`Lisans durumu: ${bannerConfig.title}`}
    >
      <div className="p-4">
        <div className="flex items-start">
          {/* Icon */}
          <div className="flex-shrink-0">
            <IconComponent 
              className={`h-5 w-5 ${bannerConfig.iconColor}`}
              aria-hidden="true"
            />
          </div>
          
          {/* Content */}
          <div className="ml-3 flex-1">
            {/* Title */}
            <h3 className={`text-sm font-medium ${bannerConfig.textColor}`}>
              {bannerConfig.title}
            </h3>
            
            {/* Message */}
            <div className={`mt-1 text-sm ${bannerConfig.textColor} opacity-90`}>
              <p>{message}</p>
              
              {/* Plan type */}
              {licenseStatus.planType && (
                <p className="mt-1">
                  <span className="font-medium">Plan:</span> {licenseStatus.planType}
                </p>
              )}
              
              {/* Countdown */}
              {showCountdown && licenseStatus.expiresAt && licenseStatus.status !== 'expired' && (
                <p className="mt-2 flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  <span>Kalan süre: </span>
                  <CountdownTimer expiresAt={licenseStatus.expiresAt} />
                </p>
              )}
            </div>
            
            {/* Actions */}
            <div className="mt-3 flex items-center gap-3">
              <Button
                size="sm"
                className={bannerConfig.buttonColor}
                onClick={handleAction}
              >
                {actionText || (
                  licenseStatus.status === 'none' ? 'Plan Seç' :
                  licenseStatus.status === 'expired' ? 'Hemen Yenile' :
                  licenseStatus.status === 'suspended' ? 'Destek Al' :
                  'Yenile'
                )}
              </Button>
              
              {/* Learn more link */}
              {licenseStatus.status !== 'suspended' && (
                <a 
                  href="/help#license"
                  className={`text-sm ${bannerConfig.textColor} opacity-75 hover:opacity-100 underline`}
                >
                  Detaylı bilgi
                </a>
              )}
            </div>
          </div>
          
          {/* Dismiss button */}
          {canDismiss && (
            <div className="ml-4 flex-shrink-0">
              <button
                type="button"
                className={`
                  rounded-md ${bannerConfig.bgColor} ${bannerConfig.textColor} 
                  hover:bg-opacity-75 focus:outline-none focus:ring-2 
                  focus:ring-offset-2 focus:ring-offset-transparent
                  focus:ring-blue-500 p-1
                `}
                onClick={handleDismiss}
                aria-label="Bildirimi kapat"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          )}
        </div>
      </div>
      
      {/* Progress bar for time-sensitive warnings */}
      {(bannerConfig.severity === 'warning' || bannerConfig.severity === 'error') && 
       licenseStatus.daysRemaining > 0 && licenseStatus.daysRemaining <= 30 && (
        <div className="px-4 pb-2">
          <div className="w-full bg-gray-200 rounded-full h-1.5">
            <div 
              className={`
                h-1.5 rounded-full transition-all duration-300
                ${bannerConfig.severity === 'error' ? 'bg-red-500' : 'bg-amber-500'}
              `}
              style={{ 
                width: `${Math.max(5, (licenseStatus.daysRemaining / 30) * 100)}%` 
              }}
              aria-label={`${licenseStatus.daysRemaining} gün kaldı`}
            />
          </div>
        </div>
      )}
    </div>
  )
}

// Convenience components for specific scenarios
export function ExpiredLicenseBanner({ licenseStatus, ...props }: Omit<LicenseBannerProps, 'licenseStatus'> & { licenseStatus: LicenseStatus }) {
  return (
    <LicenseBanner
      {...props}
      licenseStatus={licenseStatus}
      dismissible={false}
      showCountdown={false}
      actionText="Hemen Yenile"
    />
  )
}

export function TrialExpiringBanner({ licenseStatus, ...props }: Omit<LicenseBannerProps, 'licenseStatus'> & { licenseStatus: LicenseStatus }) {
  return (
    <LicenseBanner
      {...props}
      licenseStatus={licenseStatus}
      dismissible={licenseStatus.daysRemaining > 1}
      showCountdown={true}
      actionText="Plan Satın Al"
    />
  )
}

export function LicenseWarningBanner({ licenseStatus, ...props }: Omit<LicenseBannerProps, 'licenseStatus'> & { licenseStatus: LicenseStatus }) {
  return (
    <LicenseBanner
      {...props}
      licenseStatus={licenseStatus}
      dismissible={licenseStatus.daysRemaining > 7}
      showCountdown={true}
      actionText="Şimdi Yenile"
    />
  )
}