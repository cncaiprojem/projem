'use client'

import { useTranslation } from 'react-i18next'
import { SecurityNoticeProps } from '@/lib/auth-types'

export default function SecurityNotice({
  showKvkv = true,
  showDataEncryption = true,
  className = '',
}: SecurityNoticeProps) {
  const { t } = useTranslation()

  return (
    <div className={`space-y-4 ${className}`}>
      {/* KVKV Notice */}
      {showKvkv && (
        <div className="bg-blue-50 border border-blue-200 rounded-md p-4">
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
              <h3 className="text-sm font-medium text-blue-800">
                {t('auth.security.kvkkNotice')}
              </h3>
              <p className="mt-2 text-sm text-blue-700">
                {t('auth.security.kvkkText')}
              </p>
              <div className="mt-3 flex space-x-4">
                <a
                  href="/legal/privacy"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:text-blue-500 underline"
                >
                  {t('auth.security.privacyPolicy')}
                </a>
                <a
                  href="/legal/terms"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:text-blue-500 underline"
                >
                  {t('auth.security.termsOfService')}
                </a>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Security Features */}
      {showDataEncryption && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-center">
          <div className="flex flex-col items-center space-y-2">
            <div className="flex items-center justify-center w-8 h-8 bg-green-100 rounded-full">
              <svg className="w-5 h-5 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 15v2m-6 4h12a2 2 0 002-2v-9a2 2 0 00-2-2H6a2 2 0 00-2 2v9a2 2 0 002 2z"
                />
              </svg>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-900">SSL Şifreli</p>
              <p className="text-xs text-gray-500">256-bit Şifreleme</p>
            </div>
          </div>

          <div className="flex flex-col items-center space-y-2">
            <div className="flex items-center justify-center w-8 h-8 bg-blue-100 rounded-full">
              <svg className="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
                />
              </svg>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-900">KVKV Uyumlu</p>
              <p className="text-xs text-gray-500">Veri Koruması</p>
            </div>
          </div>

          <div className="flex flex-col items-center space-y-2">
            <div className="flex items-center justify-center w-8 h-8 bg-purple-100 rounded-full">
              <svg className="w-5 h-5 text-purple-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
            </div>
            <div>
              <p className="text-xs font-medium text-gray-900">Hızlı & Güvenli</p>
              <p className="text-xs text-gray-500">2FA Destekli</p>
            </div>
          </div>
        </div>
      )}

      {/* Cookie Notice */}
      <div className="text-center">
        <p className="text-xs text-gray-500">
          {t('auth.security.cookieNotice')}
        </p>
      </div>
    </div>
  )
}