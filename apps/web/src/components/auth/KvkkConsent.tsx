'use client'

import { useTranslation } from 'react-i18next'

interface KvkkConsentProps {
  accepted: boolean
  onAccept: () => void
  error?: string
  className?: string
}

export default function KvkkConsent({
  accepted,
  onAccept,
  error,
  className = '',
}: KvkkConsentProps) {
  const { t } = useTranslation()

  return (
    <div className={`space-y-3 ${className}`}>
      {/* KVKV Information */}
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
            <h4 className="text-sm font-medium text-blue-800">
              {t('auth.security.kvkkNotice')}
            </h4>
            <div className="mt-2 text-sm text-blue-700">
              <p>
                Kişisel verileriniz 6698 sayılı Kişisel Verilerin Korunması Kanunu 
                (KVKK) kapsamında işlenmektedir. Bu kapsamda:
              </p>
              <ul className="mt-2 list-disc list-inside space-y-1 text-xs">
                <li>Verileriniz güvenli şekilde saklanır ve şifrelenir</li>
                <li>Sadece hizmet sağlamak için gerekli veriler toplanır</li>
                <li>Verileriniz üçüncü taraflarla paylaşılmaz</li>
                <li>İstediğiniz zaman verilerinizi silebilirsiniz</li>
                <li>Veri işleme süreçleri hakkında bilgi alma hakkınız vardır</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      {/* Consent Checkbox */}
      <div className="flex items-start">
        <input
          id="acceptKvkk"
          type="checkbox"
          checked={accepted}
          onChange={onAccept}
          className="h-4 w-4 text-blue-600 border-gray-300 rounded focus:ring-blue-500"
        />
        <label htmlFor="acceptKvkv" className="ml-2 text-sm text-gray-700">
          <span className="font-medium">KVKK Kapsamında Açık Rıza:</span>
          <br />
          Yukarıda belirtilen amaçlar doğrultusunda kişisel verilerimin işlenmesine 
          açık rızam vererek kabul ediyorum.
        </label>
      </div>

      {error && (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      )}

      {/* Additional Information Links */}
      <div className="text-xs text-gray-500 space-y-1">
        <p>
          Daha detaylı bilgi için:{' '}
          <a
            href="/legal/kvkk"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:text-blue-500 underline"
          >
            KVKK Aydınlatma Metni
          </a>
          {' '}ve{' '}
          <a
            href="/legal/privacy"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-600 hover:text-blue-500 underline"
          >
            Gizlilik Politikası
          </a>
          'nı inceleyebilirsiniz.
        </p>
        
        <p>
          <strong>Veri Sorumlusu:</strong> FreeCAD CNC/CAM Platform<br />
          <strong>İletişim:</strong> kvkk@freecad-platform.com
        </p>
      </div>
    </div>
  )
}