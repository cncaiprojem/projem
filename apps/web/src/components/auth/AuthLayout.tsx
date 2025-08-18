'use client'

import { useTranslation } from 'react-i18next'
import { changeLanguage, getCurrentLanguage, SupportedLanguage } from '@/lib/i18n/config'
import { AuthLayoutProps } from '@/lib/auth-types'

export default function AuthLayout({
  children,
  title,
  subtitle,
  showLanguageSwitch = false,
  showSecurityNotice = true,
  className = '',
}: AuthLayoutProps) {
  const { t } = useTranslation()

  const handleLanguageChange = async (lang: SupportedLanguage) => {
    await changeLanguage(lang)
  }

  return (
    <div className={`min-h-screen bg-gray-50 flex flex-col justify-center py-12 sm:px-6 lg:px-8 ${className}`}>
      {/* Header */}
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        {/* Logo */}
        <div className="flex justify-center">
          <div className="flex items-center space-x-2">
            <div className="flex-shrink-0">
              <svg
                className="h-12 w-12 text-blue-600"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z"
                />
              </svg>
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">FreeCAD</h1>
              <p className="text-xs text-gray-500">CNC/CAM Platform</p>
            </div>
          </div>
        </div>

        {/* Language Switcher */}
        {showLanguageSwitch && (
          <div className="flex justify-center mt-4">
            <div className="inline-flex rounded-md shadow-sm" role="group">
              <button
                type="button"
                onClick={() => handleLanguageChange('tr')}
                className={`px-3 py-1 text-xs font-medium border ${
                  getCurrentLanguage() === 'tr'
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                } rounded-l-md focus:outline-none focus:ring-2 focus:ring-blue-500`}
              >
                Türkçe
              </button>
              <button
                type="button"
                onClick={() => handleLanguageChange('en')}
                className={`px-3 py-1 text-xs font-medium border-t border-b border-r ${
                  getCurrentLanguage() === 'en'
                    ? 'bg-blue-600 text-white border-blue-600'
                    : 'bg-white text-gray-700 border-gray-300 hover:bg-gray-50'
                } rounded-r-md focus:outline-none focus:ring-2 focus:ring-blue-500`}
              >
                English
              </button>
            </div>
          </div>
        )}

        {/* Title and Subtitle */}
        <div className="text-center mt-6">
          <h2 className="text-3xl font-extrabold text-gray-900">{title}</h2>
          {subtitle && (
            <p className="mt-2 text-sm text-gray-600">{subtitle}</p>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
        <div className="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
          {children}
        </div>
      </div>

      {/* Footer */}
      <div className="mt-8 text-center">
        {/* Security Indicators */}
        {showSecurityNotice && (
          <div className="flex justify-center items-center space-x-6 text-xs text-gray-500">
            <div className="flex items-center">
              <svg className="w-4 h-4 mr-1 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 15v2m-6 4h12a2 2 0 002-2v-9a2 2 0 00-2-2H6a2 2 0 00-2 2v9a2 2 0 002 2z"
                />
              </svg>
              {t('auth.security.secureConnection')}
            </div>
            
            <div className="flex items-center">
              <svg className="w-4 h-4 mr-1 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
                />
              </svg>
              {t('auth.security.dataEncryption')}
            </div>

            <div className="flex items-center">
              <svg className="w-4 h-4 mr-1 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9v-9m0-9v9"
                />
              </svg>
              KVKV Uyumlu
            </div>
          </div>
        )}

        {/* Copyright */}
        <p className="mt-4 text-xs text-gray-400">
          © 2024 FreeCAD CNC/CAM Platform. Tüm hakları saklıdır.
        </p>
      </div>
    </div>
  )
}