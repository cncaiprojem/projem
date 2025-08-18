'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import { authAPI, getErrorMessage } from '@/lib/auth-api'
import AuthLayout from '@/components/auth/AuthLayout'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

export default function MagicLinkPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const [isProcessing, setIsProcessing] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    const handleMagicLink = async () => {
      try {
        // Extract parameters from URL
        const token = searchParams?.get('token')
        const email = searchParams?.get('email')
        const redirectTo = searchParams?.get('redirect') || '/jobs'

        if (!token) {
          setError(t('auth.magicLink.linkInvalid'))
          setIsProcessing(false)
          return
        }

        // Consume the magic link token
        const response = await authAPI.consumeMagicLink({ token, email: email || undefined })

        if (response.user) {
          setSuccess(true)
          // Success - redirect after showing success message briefly
          setTimeout(() => {
            router.push(redirectTo)
          }, 2000)
        } else {
          setError(t('auth.magicLink.linkInvalid'))
          setIsProcessing(false)
        }
      } catch (err) {
        const errorMessage = getErrorMessage(err)
        setError(errorMessage)
        setIsProcessing(false)
      }
    }

    if (searchParams) {
      handleMagicLink()
    }
  }, [searchParams, router, t])

  const handleBackToLogin = () => {
    router.push('/login')
  }

  const handleRequestNewLink = () => {
    const email = searchParams?.get('email')
    if (email) {
      router.push(`/login?email=${encodeURIComponent(email)}`)
    } else {
      router.push('/login')
    }
  }

  return (
    <AuthLayout
      title={
        isProcessing
          ? t('auth.magicLink.processing')
          : success
          ? t('auth.magicLink.success')
          : t('auth.errors.generic')
      }
      subtitle={
        isProcessing
          ? 'Sihirli link işleniyor...'
          : success
          ? 'Başarıyla giriş yapıldı!'
          : undefined
      }
    >
      <div className="w-full max-w-md mx-auto">
        {isProcessing ? (
          <div className="text-center space-y-6">
            {/* Processing State */}
            <div className="flex justify-center">
              <LoadingSpinner size="large" />
            </div>
            
            <div className="space-y-2">
              <h3 className="text-lg font-medium text-gray-900">
                {t('auth.magicLink.processing')}
              </h3>
              <p className="text-sm text-gray-600">
                Giriş linkiniz doğrulanıyor...
              </p>
            </div>

            {/* Magic Link Animation */}
            <div className="flex justify-center items-center space-x-2 p-4 bg-blue-50 rounded-lg">
              <svg className="w-6 h-6 text-blue-600 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M3 8l7.89 4.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                />
              </svg>
              <div className="text-sm text-blue-600">Sihirli Link</div>
            </div>

            {/* Security Note */}
            <div className="text-xs text-gray-500">
              <div className="inline-flex items-center">
                <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 15v2m-6 4h12a2 2 0 002-2v-9a2 2 0 00-2-2H6a2 2 0 00-2 2v9a2 2 0 002 2z"
                  />
                </svg>
                Bu link tek kullanımlık ve güvenlidir
              </div>
            </div>
          </div>
        ) : success ? (
          <div className="text-center space-y-6">
            {/* Success State */}
            <div className="bg-green-50 border border-green-200 rounded-md p-6">
              <div className="flex justify-center">
                <svg
                  className="h-12 w-12 text-green-400"
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                  />
                </svg>
              </div>
              <div className="mt-3">
                <h3 className="text-lg font-medium text-green-800">
                  {t('auth.magicLink.success')}
                </h3>
                <p className="mt-2 text-sm text-green-700">
                  Ana sayfaya yönlendiriliyorsunuz...
                </p>
              </div>
            </div>

            {/* Loading indicator for redirect */}
            <div className="flex justify-center">
              <LoadingSpinner size="medium" />
            </div>
          </div>
        ) : (
          <div className="text-center space-y-6">
            {/* Error State */}
            <div className="bg-red-50 border border-red-200 rounded-md p-4">
              <div className="flex">
                <div className="flex-shrink-0">
                  <svg
                    className="h-5 w-5 text-red-400"
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
                      clipRule="evenodd"
                    />
                  </svg>
                </div>
                <div className="ml-3">
                  <h3 className="text-sm font-medium text-red-800">
                    Sihirli Link Geçersiz
                  </h3>
                  <p className="mt-2 text-sm text-red-700">{error}</p>
                </div>
              </div>
            </div>

            {/* Help Text */}
            <div className="text-sm text-gray-600">
              <p>Olası nedenler:</p>
              <ul className="mt-2 text-left space-y-1 text-xs">
                <li>• Link süresi dolmuş olabilir (15 dakika)</li>
                <li>• Link daha önce kullanılmış olabilir</li>
                <li>• Link bozuk veya eksik olabilir</li>
              </ul>
            </div>

            {/* Action Buttons */}
            <div className="space-y-3">
              <button
                onClick={handleRequestNewLink}
                className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                {t('auth.magicLink.resend')}
              </button>
              
              <button
                onClick={handleBackToLogin}
                className="w-full flex justify-center py-2 px-4 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                {t('auth.magicLink.backToLogin')}
              </button>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="mt-8 text-center">
          <div className="inline-flex items-center text-xs text-gray-500">
            <svg className="w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 15v2m-6 4h12a2 2 0 002-2v-9a2 2 0 00-2-2H6a2 2 0 00-2 2v9a2 2 0 002 2z"
              />
            </svg>
            {t('auth.security.secureConnection')}
          </div>
        </div>
      </div>
    </AuthLayout>
  )
}