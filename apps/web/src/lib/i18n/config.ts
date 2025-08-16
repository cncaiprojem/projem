import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import trTranslations from './locales/tr.json'

export const defaultNS = 'common'
export const resources = {
  tr: {
    common: trTranslations,
  },
} as const

i18n
  .use(initReactI18next)
  .init({
    lng: 'tr',
    fallbackLng: 'tr',
    defaultNS,
    resources,
    interpolation: {
      escapeValue: false,
    },
    react: {
      useSuspense: false,
    },
  })

export default i18n