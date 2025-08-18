'use client'

import { useState, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import Link from 'next/link'
import { authAPI, getErrorMessage } from '@/lib/auth-api'
import { registerSchema, RegisterFormData, PasswordStrength } from '@/lib/auth-types'
import { Button } from '@/components/ui/Button'
import AuthLayout from '@/components/auth/AuthLayout'
import FormField from '@/components/auth/FormField'
import PasswordStrengthIndicator from '@/components/auth/PasswordStrengthIndicator'
import GoogleOIDCButton from '@/components/auth/GoogleOIDCButton'
import SecurityNotice from '@/components/auth/SecurityNotice'
import KvkkConsent from '@/components/auth/KvkkConsent'

export default function RegisterPage() {
  const { t } = useTranslation()
  const router = useRouter()
  const searchParams = useSearchParams()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [passwordStrength, setPasswordStrength] = useState<PasswordStrength>(PasswordStrength.VeryWeak)

  // Get redirect URL from search params
  const redirectTo = searchParams?.get('redirect') || '/jobs'

  // React Hook Form setup
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors },
    clearErrors,
    setFocus,
    setValue,
  } = useForm<RegisterFormData>({
    resolver: zodResolver(registerSchema),
    mode: 'onBlur',
    defaultValues: {
      firstName: '',
      lastName: '',
      email: '',
      password: '',
      confirmPassword: '',
      company: '',
      acceptTerms: false,
      acceptKvkk: false,
    },
  })

  // Watch password for strength calculation
  const password = watch('password')

  // Set focus on first name field when page loads
  useEffect(() => {
    setFocus('firstName')
  }, [setFocus])

  // Calculate password strength
  useEffect(() => {
    if (password) {
      const strength = calculatePasswordStrength(password)
      setPasswordStrength(strength)
    }
  }, [password])

  // Simple password strength calculator
  const calculatePasswordStrength = (pwd: string): PasswordStrength => {
    let score = 0
    
    if (pwd.length >= 8) score += 1
    if (pwd.length >= 12) score += 1
    if (/[a-z]/.test(pwd)) score += 1
    if (/[A-Z]/.test(pwd)) score += 1
    if (/\d/.test(pwd)) score += 1
    if (/[@$!%*?&]/.test(pwd)) score += 1
    if (pwd.length >= 16) score += 1

    if (score <= 2) return PasswordStrength.VeryWeak
    if (score <= 3) return PasswordStrength.Weak
    if (score <= 4) return PasswordStrength.Fair
    if (score <= 5) return PasswordStrength.Strong
    return PasswordStrength.VeryStrong
  }

  // Handle form submission
  const onSubmit = async (data: RegisterFormData) => {
    try {
      setIsSubmitting(true)
      setError(null)
      setSuccess(null)
      clearErrors()

      const response = await authAPI.register(data)

      if (response.user) {
        setSuccess(t('auth.register.registrationSuccess'))
        
        // Wait a moment then redirect
        setTimeout(() => {
          if (response.requiresVerification) {
            router.push(`/auth/verify?email=${encodeURIComponent(data.email)}`)
          } else {
            router.push(redirectTo)
          }
        }, 2000)
      }
    } catch (err) {
      const errorMessage = getErrorMessage(err)
      setError(errorMessage)
      
      // Focus on appropriate field based on error type
      if (errorMessage.includes('E-posta') || errorMessage.includes('zaten')) {
        setFocus('email')
      } else if (errorMessage.includes('Ad')) {
        setFocus('firstName')
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

  // Handle KVKK consent acceptance
  const handleKvkkAccept = () => {
    setValue('acceptKvkk', true)
  }

  return (
    <AuthLayout
      title={t('auth.register.title')}
      subtitle={t('auth.register.subtitle')}
      showLanguageSwitch
    >
      <div className="w-full max-w-md mx-auto space-y-6">
        {success && (
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
                <p className="text-sm text-green-800">{success}</p>
              </div>
            </div>
          </div>
        )}

        {/* Google OIDC Option */}
        <div className="space-y-4">
          <GoogleOIDCButton
            text={t('auth.oauth.googleLogin')}
            redirectUrl={redirectTo}
            onSuccess={handleGoogleSuccess}
            onError={setError}
          />

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
        </div>

        {/* Registration Form */}
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {/* Name Fields */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField
              label={t('auth.register.firstName')}
              type="text"
              placeholder={t('auth.register.firstNamePlaceholder')}
              error={errors.firstName?.message}
              autoComplete="given-name"
              autoFocus
              {...register('firstName')}
            />

            <FormField
              label={t('auth.register.lastName')}
              type="text"
              placeholder={t('auth.register.lastNamePlaceholder')}
              error={errors.lastName?.message}
              autoComplete="family-name"
              {...register('lastName')}
            />
          </div>

          {/* Email Field */}
          <FormField
            label={t('auth.register.email')}
            type="email"
            placeholder={t('auth.register.emailPlaceholder')}
            error={errors.email?.message}
            autoComplete="email"
            {...register('email')}
          />

          {/* Company Field (Optional) */}
          <FormField
            label={t('auth.register.company')}
            type="text"
            placeholder={t('auth.register.companyPlaceholder')}
            error={errors.company?.message}
            autoComplete="organization"
            required={false}
            {...register('company')}
          />

          {/* Password Field with Strength Indicator */}
          <div className="space-y-2">
            <FormField
              label={t('auth.register.password')}
              type="password"
              placeholder={t('auth.register.passwordPlaceholder')}
              error={errors.password?.message}
              autoComplete="new-password"
              {...register('password')}
            />
            {password && (
              <PasswordStrengthIndicator
                password={password}
                strength={passwordStrength}
              />
            )}
          </div>

          {/* Confirm Password Field */}
          <FormField
            label={t('auth.register.confirmPassword')}
            type="password"
            placeholder={t('auth.register.confirmPasswordPlaceholder')}
            error={errors.confirmPassword?.message}
            autoComplete="new-password"
            {...register('confirmPassword')}
          />

          {/* Terms and KVKK Acceptance */}
          <div className="space-y-3">
            {/* Terms of Service */}
            <div className="flex items-start">
              <input
                id="acceptTerms"
                type="checkbox"
                className="h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
                {...register('acceptTerms')}
              />
              <label htmlFor="acceptTerms" className="ml-2 text-sm text-gray-700">
                {t('auth.register.acceptTerms')}{' '}
                <Link
                  href="/legal/terms"
                  target="_blank"
                  className="text-blue-600 hover:text-blue-500"
                >
                  {t('auth.security.termsOfService')}
                </Link>
                {' '}{t('app.and')}{' '}
                <Link
                  href="/legal/privacy"
                  target="_blank"
                  className="text-blue-600 hover:text-blue-500"
                >
                  {t('auth.security.privacyPolicy')}
                </Link>
              </label>
            </div>
            {errors.acceptTerms && (
              <p className="text-sm text-red-600">{errors.acceptTerms.message}</p>
            )}

            {/* KVKK Consent */}
            <KvkkConsent
              accepted={watch('acceptKvkk')}
              onAccept={handleKvkkAccept}
              error={errors.acceptKvkk?.message}
            />
          </div>

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
            disabled={isSubmitting || success !== null}
            loading={isSubmitting}
          >
            {isSubmitting
              ? t('auth.register.registrationInProgress')
              : t('auth.register.submit')}
          </Button>
        </form>

        {/* Sign In Link */}
        <div className="text-center">
          <p className="text-sm text-gray-600">
            {t('auth.register.hasAccount')}{' '}
            <Link
              href={`/login${redirectTo !== '/jobs' ? `?redirect=${encodeURIComponent(redirectTo)}` : ''}`}
              className="font-medium text-blue-600 hover:text-blue-500"
            >
              {t('auth.register.signIn')}
            </Link>
          </p>
        </div>

        {/* Security Notice */}
        <SecurityNotice showKvkv showDataEncryption className="mt-8" />
      </div>
    </AuthLayout>
  )
}