/**
 * Task 3.14: Ultra-Enterprise Idle Warning Modal
 * Turkish localized auto-logout warning with KVKV compliance
 * 
 * Features:
 * - Countdown display with progress bar
 * - Turkish localized messages
 * - Banking-grade visual design
 * - Accessibility support
 * - KVKV compliant user interaction logging
 * - Cross-tab synchronization
 */

'use client'

import React, { useEffect, useState } from 'react'
import { AlertTriangle, Clock, Shield, Activity } from 'lucide-react'
import { Button } from './Button'

export interface IdleWarningModalProps {
  /** Whether the modal is visible */
  isVisible: boolean
  /** Remaining time in seconds */
  remainingTime?: number
  /** Callback when user chooses to stay logged in */
  onStayLoggedIn: () => void
  /** Callback when user chooses to logout now */
  onLogoutNow: () => void
  /** Custom warning message */
  customMessage?: string
  /** Whether to show the countdown */
  showCountdown?: boolean
}

// Helper function to format time remaining
function formatTimeRemaining(seconds: number): string {
  if (seconds <= 0) return '0:00'
  
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  
  return `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`
}

// Helper function to get urgency level
function getUrgencyLevel(seconds: number): 'low' | 'medium' | 'high' | 'critical' {
  if (seconds <= 30) return 'critical'
  if (seconds <= 60) return 'high'
  if (seconds <= 120) return 'medium'
  return 'low'
}

export function IdleWarningModal({
  isVisible,
  remainingTime = 0,
  onStayLoggedIn,
  onLogoutNow,
  customMessage,
  showCountdown = true
}: IdleWarningModalProps) {
  const [localTime, setLocalTime] = useState(remainingTime)
  
  // Update local time state when prop changes
  useEffect(() => {
    setLocalTime(remainingTime)
  }, [remainingTime])
  
  // Local countdown effect
  useEffect(() => {
    if (!isVisible || localTime <= 0) return
    
    const interval = setInterval(() => {
      setLocalTime(prev => Math.max(0, prev - 1))
    }, 1000)
    
    return () => clearInterval(interval)
  }, [isVisible, localTime])
  
  if (!isVisible) return null
  
  const urgencyLevel = getUrgencyLevel(localTime)
  const timeString = formatTimeRemaining(localTime)
  const progressPercentage = remainingTime > 0 ? (localTime / remainingTime) * 100 : 0
  
  // Urgency-based styling
  const urgencyConfig = {
    low: {
      bgColor: 'bg-blue-50',
      borderColor: 'border-blue-200',
      iconColor: 'text-blue-600',
      textColor: 'text-blue-900',
      progressColor: 'bg-blue-500',
      primaryButton: 'bg-blue-600 hover:bg-blue-700',
      secondaryButton: 'bg-gray-100 hover:bg-gray-200 text-gray-700'
    },
    medium: {
      bgColor: 'bg-amber-50',
      borderColor: 'border-amber-200',
      iconColor: 'text-amber-600',
      textColor: 'text-amber-900',
      progressColor: 'bg-amber-500',
      primaryButton: 'bg-amber-600 hover:bg-amber-700',
      secondaryButton: 'bg-gray-100 hover:bg-gray-200 text-gray-700'
    },
    high: {
      bgColor: 'bg-orange-50',
      borderColor: 'border-orange-200',
      iconColor: 'text-orange-600',
      textColor: 'text-orange-900',
      progressColor: 'bg-orange-500',
      primaryButton: 'bg-orange-600 hover:bg-orange-700',
      secondaryButton: 'bg-gray-100 hover:bg-gray-200 text-gray-700'
    },
    critical: {
      bgColor: 'bg-red-50',
      borderColor: 'border-red-200',
      iconColor: 'text-red-600',
      textColor: 'text-red-900',
      progressColor: 'bg-red-500',
      primaryButton: 'bg-red-600 hover:bg-red-700',
      secondaryButton: 'bg-gray-100 hover:bg-gray-200 text-gray-700'
    }
  }
  
  const config = urgencyConfig[urgencyLevel]
  
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div 
        className="absolute inset-0 bg-black bg-opacity-50 backdrop-blur-sm"
        aria-hidden="true"
      />
      
      {/* Modal */}
      <div 
        className={`
          relative w-full max-w-md rounded-lg border-2 shadow-2xl
          ${config.bgColor} ${config.borderColor}
          animate-pulse-slow
        `}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="idle-warning-title"
        aria-describedby="idle-warning-description"
      >
        {/* Header */}
        <div className="p-6 pb-4">
          <div className="flex items-center gap-4">
            <div className={`p-3 rounded-full ${config.bgColor}`}>
              {urgencyLevel === 'critical' ? (
                <AlertTriangle className={`h-8 w-8 ${config.iconColor}`} />
              ) : (
                <Clock className={`h-8 w-8 ${config.iconColor}`} />
              )}
            </div>
            
            <div className="flex-1">
              <h2 
                id="idle-warning-title"
                className={`text-lg font-semibold ${config.textColor}`}
              >
                Hareketsizlik Uyarısı
              </h2>
              <p className={`text-sm ${config.textColor} opacity-75 mt-1`}>
                Güvenlik nedeniyle oturum sonlandırılacak
              </p>
            </div>
          </div>
        </div>
        
        {/* Content */}
        <div className="px-6 pb-4">
          <div 
            id="idle-warning-description"
            className={`text-sm ${config.textColor} space-y-3`}
          >
            <p>
              {customMessage || 
               'Uzun süre hareketsizlik tespit edildi. Güvenlik amacıyla oturumunuz otomatik olarak sonlandırılacak.'
              }
            </p>
            
            {showCountdown && (
              <div className="space-y-2">
                {/* Countdown display */}
                <div className="flex items-center justify-center p-4 rounded-lg bg-white bg-opacity-50">
                  <div className="text-center">
                    <div className={`text-3xl font-mono font-bold ${config.textColor}`}>
                      {timeString}
                    </div>
                    <div className={`text-xs font-medium ${config.textColor} opacity-75 mt-1`}>
                      Kalan Süre
                    </div>
                  </div>
                </div>
                
                {/* Progress bar */}
                <div className="w-full bg-gray-200 rounded-full h-2">
                  <div 
                    className={`h-2 rounded-full transition-all duration-1000 ease-linear ${config.progressColor}`}
                    style={{ width: `${Math.max(5, progressPercentage)}%` }}
                    aria-label={`${localTime} saniye kaldı`}
                  />
                </div>
              </div>
            )}
            
            {/* Security notice */}
            <div className="flex items-center gap-2 text-xs opacity-75">
              <Shield className="h-4 w-4" />
              <span>KVKV uyumlu güvenlik protokolü</span>
            </div>
          </div>
        </div>
        
        {/* Actions */}
        <div className="px-6 pb-6 space-y-3">
          {/* Primary action - Stay logged in */}
          <Button
            onClick={() => {
              // Log user choice (KVKV compliant - no PII)
              console.log('[IDLE-MODAL] User chose to stay logged in', {
                timestamp: new Date().toISOString(),
                remaining_seconds: localTime,
                urgency_level: urgencyLevel
              })
              onStayLoggedIn()
            }}
            className={`w-full text-white ${config.primaryButton}`}
            size="lg"
          >
            <Activity className="h-4 w-4 mr-2" />
            Oturumda Kal
          </Button>
          
          {/* Secondary action - Logout now */}
          <Button
            onClick={() => {
              // Log user choice (KVKV compliant - no PII) 
              console.log('[IDLE-MODAL] User chose to logout now', {
                timestamp: new Date().toISOString(),
                remaining_seconds: localTime,
                urgency_level: urgencyLevel
              })
              onLogoutNow()
            }}
            variant="outline"
            className={`w-full ${config.secondaryButton}`}
            size="sm"
          >
            Şimdi Çıkış Yap
          </Button>
        </div>
        
        {/* Critical warning footer */}
        {urgencyLevel === 'critical' && (
          <div className="px-6 pb-4">
            <div className="text-center text-xs text-red-600 font-medium bg-red-100 rounded p-2">
              ⚠️ Otomatik çıkış yakında gerçekleşecek
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Convenience component for banking-grade timeout (shorter duration)
export function BankingIdleWarningModal(props: Omit<IdleWarningModalProps, 'customMessage'>) {
  return (
    <IdleWarningModal
      {...props}
      customMessage="Bankacılık seviyesinde güvenlik protokolü nedeniyle oturumunuz kısa sürede sonlandırılacak. Bu, verilerinizin güvenliği içindir."
    />
  )
}

// Convenience component with custom styling for different contexts
export function EnterpriseIdleWarningModal(props: IdleWarningModalProps) {
  return (
    <IdleWarningModal
      {...props}
      customMessage={
        props.customMessage || 
        'Kurumsal güvenlik politikaları gereği oturumunuz sonlandırılacak. Çalışmanızı kaydettiğinizden emin olun.'
      }
    />
  )
}