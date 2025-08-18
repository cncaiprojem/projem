'use client'

import { PasswordStrength } from '@/lib/auth-types'

interface PasswordStrengthIndicatorProps {
  password: string
  strength: PasswordStrength
  className?: string
}

export default function PasswordStrengthIndicator({
  password,
  strength,
  className = '',
}: PasswordStrengthIndicatorProps) {
  if (!password) return null

  const getStrengthConfig = (strength: PasswordStrength) => {
    switch (strength) {
      case PasswordStrength.VeryWeak:
        return {
          color: 'bg-red-500',
          width: '20%',
          text: 'Çok Zayıf',
          textColor: 'text-red-600',
        }
      case PasswordStrength.Weak:
        return {
          color: 'bg-red-400',
          width: '40%',
          text: 'Zayıf',
          textColor: 'text-red-600',
        }
      case PasswordStrength.Fair:
        return {
          color: 'bg-yellow-400',
          width: '60%',
          text: 'Orta',
          textColor: 'text-yellow-600',
        }
      case PasswordStrength.Strong:
        return {
          color: 'bg-green-400',
          width: '80%',
          text: 'Güçlü',
          textColor: 'text-green-600',
        }
      case PasswordStrength.VeryStrong:
        return {
          color: 'bg-green-500',
          width: '100%',
          text: 'Çok Güçlü',
          textColor: 'text-green-600',
        }
      default:
        return {
          color: 'bg-gray-300',
          width: '0%',
          text: '',
          textColor: 'text-gray-500',
        }
    }
  }

  const getPasswordRequirements = (password: string) => {
    const requirements = [
      {
        text: 'En az 8 karakter',
        met: password.length >= 8,
      },
      {
        text: 'Büyük harf (A-Z)',
        met: /[A-Z]/.test(password),
      },
      {
        text: 'Küçük harf (a-z)',
        met: /[a-z]/.test(password),
      },
      {
        text: 'Sayı (0-9)',
        met: /\d/.test(password),
      },
      {
        text: 'Özel karakter (@$!%*?&)',
        met: /[@$!%*?&]/.test(password),
      },
    ]

    return requirements
  }

  const strengthConfig = getStrengthConfig(strength)
  const requirements = getPasswordRequirements(password)

  return (
    <div className={`space-y-3 ${className}`}>
      {/* Strength Bar */}
      <div>
        <div className="flex justify-between items-center mb-1">
          <span className="text-sm font-medium text-gray-700">Şifre Gücü</span>
          <span className={`text-sm font-medium ${strengthConfig.textColor}`}>
            {strengthConfig.text}
          </span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className={`h-2 rounded-full transition-all duration-300 ${strengthConfig.color}`}
            style={{ width: strengthConfig.width }}
          />
        </div>
      </div>

      {/* Requirements Checklist */}
      <div className="space-y-1">
        <p className="text-xs font-medium text-gray-700 mb-2">Şifre Gereksinimleri:</p>
        {requirements.map((req, index) => (
          <div key={index} className="flex items-center space-x-2">
            <div className={`flex-shrink-0 w-4 h-4 rounded-full flex items-center justify-center ${
              req.met 
                ? 'bg-green-100 text-green-600' 
                : 'bg-gray-100 text-gray-400'
            }`}>
              {req.met ? (
                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 13l4 4L19 7"
                  />
                </svg>
              ) : (
                <div className="w-2 h-2 bg-current rounded-full" />
              )}
            </div>
            <span className={`text-xs ${
              req.met ? 'text-green-600' : 'text-gray-500'
            }`}>
              {req.text}
            </span>
          </div>
        ))}
      </div>

      {/* Security Tips */}
      {strength === PasswordStrength.VeryWeak || strength === PasswordStrength.Weak ? (
        <div className="bg-yellow-50 border border-yellow-200 rounded-md p-2">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg
                className="h-4 w-4 text-yellow-400"
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
            <div className="ml-2">
              <p className="text-xs text-yellow-800">
                <strong>Güvenlik Önerisi:</strong> Daha güçlü bir şifre için yukarıdaki 
                tüm gereksinimleri karşılamaya çalışın.
              </p>
            </div>
          </div>
        </div>
      ) : strength === PasswordStrength.VeryStrong ? (
        <div className="bg-green-50 border border-green-200 rounded-md p-2">
          <div className="flex">
            <div className="flex-shrink-0">
              <svg
                className="h-4 w-4 text-green-400"
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
            <div className="ml-2">
              <p className="text-xs text-green-800">
                <strong>Mükemmel!</strong> Şifreniz çok güçlü ve güvenli.
              </p>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}