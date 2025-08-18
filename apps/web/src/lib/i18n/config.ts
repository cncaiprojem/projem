import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import trTranslations from './locales/tr.json'
import enTranslations from './locales/en.json'

export const defaultNS = 'common'
export const fallbackNS = 'common'

export const resources = {
  tr: {
    common: trTranslations,
  },
  en: {
    common: enTranslations,
  },
} as const

export const supportedLanguages = ['tr', 'en'] as const
export type SupportedLanguage = typeof supportedLanguages[number]

// Language detection options
const detectionOptions = {
  order: ['localStorage', 'navigator', 'htmlTag'],
  lookupLocalStorage: 'i18nextLng',
  caches: ['localStorage'],
}

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    lng: 'tr', // Default to Turkish
    fallbackLng: 'en', // Fallback to English
    supportedLngs: supportedLanguages,
    defaultNS,
    fallbackNS,
    resources,
    detection: detectionOptions,
    interpolation: {
      escapeValue: false, // React already does escaping
    },
    react: {
      useSuspense: false, // Avoid suspense for SSR compatibility
    },
    // Development options
    debug: process.env.NODE_ENV === 'development',
    saveMissing: process.env.NODE_ENV === 'development',
    missingKeyHandler: (lng, ns, key) => {
      if (process.env.NODE_ENV === 'development') {
        console.warn(`Missing translation key: ${lng}:${ns}:${key}`)
      }
    },
  })

// Export utility functions
export const getCurrentLanguage = (): SupportedLanguage => {
  const current = i18n.language as SupportedLanguage
  return supportedLanguages.includes(current) ? current : 'tr'
}

export const changeLanguage = (lang: SupportedLanguage): Promise<void> => {
  return i18n.changeLanguage(lang)
}

export const isRTL = (lang?: string): boolean => {
  // Turkish and English are LTR languages
  return false
}

export default i18n