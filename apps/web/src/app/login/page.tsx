'use client'

import { useState, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import Link from 'next/link'
import { authAPI, getErrorMessage } from '@/lib/auth-api'
import { loginSchema, LoginFormData } from '@/lib/auth-types'
import { Button } from '@/components/ui/Button'
import AuthLayout from '@/components/auth/AuthLayout'
import FormField from '@/components/auth/FormField'
import GoogleOIDCButton from '@/components/auth/GoogleOIDCButton'
import MagicLinkSection from '@/components/auth/MagicLinkSection'
import SecurityNotice from '@/components/auth/SecurityNotice'

export default function LoginPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showMagicLink, setShowMagicLink] = useState(false)

  // Get redirect URL from search params
  const redirectTo = searchParams?.get('redirect') || '/jobs'
  const from = searchParams?.get('from')

  // React Hook Form setup
  const {
    register,
    handleSubmit,
    formState: { errors },
    clearErrors,
    setFocus,
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
    mode: 'onBlur',
    defaultValues: {
      email: '',
      password: '',
    },
  })

  // Set focus on email field when page loads
  useEffect(() => {
    setFocus('email')
  }, [setFocus])

  // Handle form submission
  const onSubmit = async (data: LoginFormData) => {
    try {
      setIsSubmitting(true)
      setError(null)
      clearErrors()

      const response = await authAPI.login(data)

      if (response.user) {
        // Success - redirect to intended page
        router.push(redirectTo)
      } else if (response.requiresVerification) {
        // Account needs verification
        router.push(`/auth/verify?email=${encodeURIComponent(data.email)}`)
      }
    } catch (err) {
      const errorMessage = getErrorMessage(err)
      setError(errorMessage)
      
      // Focus on appropriate field based on error type
      if (errorMessage.includes('E-posta')) {
        setFocus('email')
      } else if (errorMessage.includes('şifre')) {
        setFocus('password')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  // Handle Google OIDC success
  const handleGoogleSuccess = () => {
    router.push(redirectTo)
  }

  // Handle Magic Link success
  const handleMagicLinkSuccess = () => {
    setShowMagicLink(false)
    // Magic link will be handled via email, show success message
  }

  return (
    <AuthLayout
      title={t('auth.login.title')}
      subtitle={t('auth.login.subtitle')}
      showLanguageSwitch
    >
      <div className="w-full max-w-md mx-auto space-y-6">
        {/* Display contextual messages */}
        {from === 'expired' && (
          <div className="bg-yellow-50 border border-yellow-200 rounded-md p-4">
            <div className="flex">
              <div className="flex-shrink-0">
                <svg
                  className="h-5 w-5 text-yellow-400"
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 20 20"
                  fill="currentColor"
                >
                  <path
                    fillRule="evenodd"
                    d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z"
                    clipRule="evenodd"
                  />
                </svg>
              </div>
              <div className="ml-3">
                <p className="text-sm text-yellow-800">
                  {t('auth.errors.sessionExpired')}
                </p>
              </div>
            </div>
          </div>
        )}

        {!showMagicLink ? (
          <>
            {/* Standard Login Form */}
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
              <FormField
                label={t('auth.login.email')}
                type="email"
                placeholder={t('auth.login.emailPlaceholder')}
                error={errors.email?.message}
                autoComplete="email"
                autoFocus
                {...register('email')}
              />

              <FormField
                label={t('auth.login.password')}
                type="password"
                placeholder={t('auth.login.passwordPlaceholder')}
                error={errors.password?.message}
                autoComplete="current-password"
                {...register('password')}
              />

              {error && (
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
                      <p className="text-sm text-red-800">{error}</p>
                    </div>
                  </div>
                </div>
              )}

              <Button
                type="submit"
                className="w-full"
                disabled={isSubmitting}
                loading={isSubmitting}
              >
                {isSubmitting ? t('auth.login.loginInProgress') : t('auth.login.submit')}
              </Button>
            </form>

            {/* Forgot Password Link */}
            <div className="text-center">
              <button
                type="button"
                onClick={() => setShowMagicLink(true)}
                className="text-sm text-blue-600 hover:text-blue-500 font-medium"
              >
                {t('auth.login.forgotPassword')}
              </button>
            </div>

            {/* Divider */}
            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-gray-300" />
              </div>
              <div className="relative flex justify-center text-sm">
                <span className="px-2 bg-white text-gray-500">
                  {t('auth.login.orContinueWith')}
                </span>
              </div>
            </div>

            {/* Alternative Login Methods */}
            <div className="space-y-3">
              <GoogleOIDCButton
                redirectUrl={redirectTo}
                onSuccess={handleGoogleSuccess}
                onError={setError}
              />

              <button
                type="button"
                onClick={() => setShowMagicLink(true)}
                className="w-full flex justify-center items-center px-4 py-2 border border-gray-300 rounded-md shadow-sm text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                <svg
                  className="w-5 h-5 mr-2"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M3 8l7.89 4.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
                  />
                </svg>
                {t('auth.login.magicLinkLogin')}
              </button>
            </div>

            {/* Register Link */}
            <div className="text-center">
              <p className="text-sm text-gray-600">
                {t('auth.login.noAccount')}{' '}
                <Link
                  href={`/register${redirectTo !== '/jobs' ? `?redirect=${encodeURIComponent(redirectTo)}` : ''}`}
                  className="font-medium text-blue-600 hover:text-blue-500"
                >
                  {t('auth.login.createAccount')}
                </Link>
              </p>
            </div>
          </>
        ) : (
          <>
            {/* Magic Link Section */}
            <MagicLinkSection
              onSuccess={handleMagicLinkSuccess}
              onError={setError}
              onBack={() => setShowMagicLink(false)}
            />
          </>
        )}

        {/* Security Notice */}
        <SecurityNotice showKvkk showDataEncryption className="mt-8" />
      </div>
    </AuthLayout>
  )
}