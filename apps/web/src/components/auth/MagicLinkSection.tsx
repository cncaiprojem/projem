'use client'

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { authAPI, getErrorMessage } from '@/lib/auth-api'
import { magicLinkRequestSchema, MagicLinkRequestData } from '@/lib/auth-types'
import { Button } from '@/components/ui/Button'
import FormField from './FormField'

interface MagicLinkSectionProps {
  onSuccess?: () => void
  onError?: (error: string) => void
  onBack?: () => void
  className?: string
}

export default function MagicLinkSection({
  onSuccess,
  onError,
  onBack,
  className = '',
}: MagicLinkSectionProps) {
  const { t } = useTranslation()
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [emailSent, setEmailSent] = useState(false)
  const [sentToEmail, setSentToEmail] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    formState: { errors },
    getValues,
  } = useForm<MagicLinkRequestData>({
    resolver: zodResolver(magicLinkRequestSchema),
    mode: 'onBlur',
  })

  const handleMagicLinkRequest = async (data: MagicLinkRequestData) => {
    try {
      setIsSubmitting(true)
      onError?.('')

      await authAPI.requestMagicLink(data)

      setEmailSent(true)
      setSentToEmail(data.email)
      onSuccess?.()
    } catch (err) {
      const errorMessage = getErrorMessage(err)
      onError?.(errorMessage)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleResend = async () => {
    const email = sentToEmail || getValues('email')
    if (email) {
      await handleMagicLinkRequest({ email })
    }
  }

  if (emailSent) {
    return (
      <div className={`space-y-6 ${className}`}>
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
                {t('auth.magicLink.emailSent')}
              </h3>
              <p className="mt-2 text-sm text-green-700">
                {t('auth.magicLink.checkInbox', { email: sentToEmail })}
              </p>
            </div>
          </div>
        </div>

        {/* Instructions */}
        <div className="text-center space-y-4">
          <div className="flex justify-center">
            <svg className="w-16 h-16 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M3 8l7.89 4.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
              />
            </svg>
          </div>

          <div className="text-sm text-gray-600 space-y-2">
            <p>E-postanızı kontrol edin ve giriş linkine tıklayın.</p>
            <p className="text-xs">Link 15 dakika geçerlidir.</p>
          </div>

          <div className="space-y-3">
            <button
              onClick={handleResend}
              disabled={isSubmitting}
              className="text-sm text-blue-600 hover:text-blue-500 font-medium disabled:opacity-50"
            >
              {isSubmitting ? 'Gönderiliyor...' : t('auth.magicLink.resend')}
            </button>

            <div>
              <button
                onClick={onBack}
                className="text-sm text-gray-600 hover:text-gray-500"
              >
                {t('auth.magicLink.backToLogin')}
              </button>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className={`space-y-6 ${className}`}>
      {/* Header */}
      <div className="text-center">
        <div className="flex justify-center mb-4">
          <svg className="w-12 h-12 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M3 8l7.89 4.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
            />
          </svg>
        </div>
        <h3 className="text-lg font-medium text-gray-900">
          {t('auth.magicLink.title')}
        </h3>
        <p className="text-sm text-gray-600 mt-2">
          {t('auth.magicLink.description')}
        </p>
      </div>

      {/* Form */}
      <form onSubmit={handleSubmit(handleMagicLinkRequest)} className="space-y-4">
        <FormField
          label={t('auth.login.email')}
          type="email"
          placeholder={t('auth.login.emailPlaceholder')}
          error={errors.email?.message}
          autoComplete="email"
          autoFocus
          {...register('email')}
        />

        <Button
          type="submit"
          className="w-full"
          disabled={isSubmitting}
          loading={isSubmitting}
        >
          {isSubmitting ? 'Gönderiliyor...' : t('auth.login.sendMagicLink')}
        </Button>
      </form>

      {/* Back Button */}
      <div className="text-center">
        <button
          onClick={onBack}
          className="text-sm text-gray-600 hover:text-gray-500"
        >
          ← {t('auth.magicLink.backToLogin')}
        </button>
      </div>

      {/* Info */}
      <div className="bg-blue-50 border border-blue-200 rounded-md p-3">
        <div className="flex">
          <div className="flex-shrink-0">
            <svg
              className="h-5 w-5 text-blue-400"
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 20 20"
              fill="currentColor"
            >
              <path
                fillRule="evenodd"
                d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                clipRule="evenodd"
              />
            </svg>
          </div>
          <div className="ml-3">
            <p className="text-sm text-blue-700">
              <strong>Sihirli Link Nedir?</strong><br />
              Size özel ve güvenli bir giriş linki gönderiyoruz. Bu link tek kullanımlık 
              olup 15 dakika geçerlidir. Şifre girmeden güvenli şekilde giriş yapabilirsiniz.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}