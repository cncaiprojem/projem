/**
 * Magic Link Authentication Hook
 * Ultra-enterprise passwordless authentication with Turkish error handling
 */

import { useState, useCallback } from 'react'
import { authAPI, getErrorMessage, tokenManager } from '@/lib/auth-api'
import { UseMagicLinkReturn } from '@/lib/auth-types'

export function useMagicLink(): UseMagicLinkReturn {
  const [isRequesting, setIsRequesting] = useState(false)
  const [isConsuming, setIsConsuming] = useState(false)
  const [emailSent, setEmailSent] = useState(false)
  const [sentToEmail, setSentToEmail] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)

  // Request magic link
  const requestMagicLink = useCallback(async (email: string) => {
    try {
      setIsRequesting(true)
      setError(null)
      setSuccess(null)

      const response = await authAPI.requestMagicLink({ email })
      
      setEmailSent(true)
      setSentToEmail(email)
      setSuccess(response.message || 'Sihirli link gönderildi!')
    } catch (err) {
      const errorMessage = getErrorMessage(err)
      setError(errorMessage)
      throw err
    } finally {
      setIsRequesting(false)
    }
  }, [])

  // Consume magic link token
  const consumeMagicLink = useCallback(async (token: string, email?: string) => {
    try {
      setIsConsuming(true)
      setError(null)
      setSuccess(null)

      const response = await authAPI.consumeMagicLink({ 
        token, 
        email: email || sentToEmail || undefined 
      })

      if (response.user && response.access_token) {
        // Store access token
        tokenManager.setToken(response.access_token)
        setSuccess('Sihirli link ile başarıyla giriş yapıldı!')
        
        // Success - the calling component should handle navigation
        return response
      } else {
        throw new Error('Invalid response from magic link consumption')
      }
    } catch (err) {
      const errorMessage = getErrorMessage(err)
      setError(errorMessage)
      throw err
    } finally {
      setIsConsuming(false)
    }
  }, [sentToEmail])

  // Resend magic link
  const resendMagicLink = useCallback(async () => {
    if (!sentToEmail) {
      setError('Yeniden göndermek için önce bir e-posta adresi girin')
      return
    }

    await requestMagicLink(sentToEmail)
  }, [sentToEmail, requestMagicLink])

  // Clear all state
  const clearState = useCallback(() => {
    setIsRequesting(false)
    setIsConsuming(false)
    setEmailSent(false)
    setSentToEmail(null)
    setError(null)
    setSuccess(null)
  }, [])

  return {
    isRequesting,
    isConsuming,
    emailSent,
    sentToEmail,
    error,
    success,
    requestMagicLink,
    consumeMagicLink,
    resendMagicLink,
    clearState,
  }
}