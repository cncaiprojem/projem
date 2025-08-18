'use client'

import { useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import { authAPI, getErrorMessage } from '@/lib/auth-api'
import AuthLayout from '@/components/auth/AuthLayout'
import LoadingSpinner from '@/components/ui/LoadingSpinner'

export default function OIDCCallbackPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const [isProcessing, setIsProcessing] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const handleCallback = async () => {
      try {
        // Extract parameters from URL
        const code = searchParams?.get('code')
        const state = searchParams?.get('state')
        const errorParam = searchParams?.get('error')
        const errorDescription = searchParams?.get('error_description')

        // Check for OAuth errors first
        if (errorParam) {
          if (errorParam === 'access_denied') {
            setError(t('auth.oauth.cancelled'))
          } else {
            setError(errorDescription || t('auth.oauth.failed'))
          }
          setIsProcessing(false)
          return
        }

        // Validate required parameters
        if (!code || !state) {
          setError(t('auth.errors.invalidToken'))
          setIsProcessing(false)
          return
        }

        // Get redirect URL from state (if encoded) or use default
        let redirectUrl = '/jobs'
        try {
          const stateData = JSON.parse(atob(state))
          if (stateData.redirect_url) {
            redirectUrl = stateData.redirect_url
          }
        } catch {
          // State might not be base64 encoded JSON, use as-is or default
        }

        // Handle the OIDC callback
        const response = await authAPI.handleGoogleOIDCCallback(code, state, redirectUrl)

        if (response.user) {
          // Success - redirect after showing success message briefly
          setTimeout(() => {
            router.push(redirectUrl)
          }, 1500)
        } else {
          setError(t('auth.oauth.failed'))
          setIsProcessing(false)
        }
      } catch (err) {
        const errorMessage = getErrorMessage(err)
        setError(errorMessage)
        setIsProcessing(false)
      }
    }

    if (searchParams) {
      handleCallback()
    }
  }, [searchParams, router, t])

  const handleRetry = () => {
    setError(null)
    setIsProcessing(true)
    // Retry the callback process
    window.location.reload()
  }

  const handleBackToLogin = () => {
    router.push('/login')
  }

  return (
    <AuthLayout
      title={isProcessing ? t('auth.oauth.processing') : t('auth.oauth.failed')}
      subtitle={
        isProcessing
          ? 'Google ile giriş işleminiz tamamlanıyor...'
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
                {t('auth.oauth.processing')}
              </h3>
              <p className="text-sm text-gray-600">
                Google hesabınızla giriş yapılıyor...
              </p>
            </div>

            {/* Google Logo Animation */}
            <div className="flex justify-center items-center space-x-2 p-4 bg-gray-50 rounded-lg">
              <svg className="w-6 h-6" viewBox="0 0 24 24">
                <path
                  fill="#4285F4"
                  d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                />
                <path
                  fill="#34A853"
                  d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                />
                <path
                  fill="#FBBC05"
                  d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                />
                <path
                  fill="#EA4335"
                  d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                />
              </svg>
              <div className="text-sm text-gray-600">Google</div>
            </div>
          </div>
        ) : error ? (
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
                    {t('auth.oauth.failed')}
                  </h3>
                  <p className="mt-2 text-sm text-red-700">{error}</p>
                </div>
              </div>
            </div>

            {/* Action Buttons */}
            <div className="space-y-3">
              <button
                onClick={handleRetry}
                className="w-full flex justify-center py-2 px-4 border border-transparent rounded-md shadow-sm text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                {t('app.retry')}
              </button>
              
              <button
                onClick={handleBackToLogin}
                className="w-full flex justify-center py-2 px-4 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                {t('auth.magicLink.backToLogin')}
              </button>
            </div>
          </div>
        ) : (
          <div className="text-center space-y-6">
            {/* Success State */}
            <div className="bg-green-50 border border-green-200 rounded-md p-4">
              <div className="flex">
                <div className="flex-shrink-0">
                  <svg
                    className="h-5 w-5 text-green-400"
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                  >
                    <path
                      fillRule="evenodd"
                      d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                      clipRule="evenodd"
                    />
                  </svg>
                </div>
                <div className="ml-3">
                  <h3 className="text-sm font-medium text-green-800">
                    {t('auth.oauth.success')}
                  </h3>
                  <p className="mt-2 text-sm text-green-700">
                    Yönlendiriliyorsunuz...
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Security Notice */}
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