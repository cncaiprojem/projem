/**
 * Google OIDC Authentication Hook
 * Ultra-enterprise Google OAuth integration with Turkish error handling
 */

import { useState, useCallback } from 'react'
import { authAPI, getErrorMessage, tokenManager } from '@/lib/auth-api'
import { UseGoogleOIDCReturn } from '@/lib/auth-types'

export function useGoogleOIDC(): UseGoogleOIDCReturn {
  const [isProcessing, setIsProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [redirectUrl, setRedirectUrl] = useState<string | undefined>()

  // Initiate Google OIDC login
  const initiateLogin = useCallback(async (redirectTo?: string) => {
    try {
      setIsProcessing(true)
      setError(null)
      setRedirectUrl(redirectTo)

      const response = await authAPI.initiateGoogleOIDC(redirectTo)
      
      if (response.authorization_url) {
        // Redirect to Google OAuth
        window.location.href = response.authorization_url
      } else {
        throw new Error('No authorization URL received from server')
      }
    } catch (err) {
      const errorMessage = getErrorMessage(err)
      setError(errorMessage)
      setIsProcessing(false)
    }
  }, [])

  // Handle OAuth callback
  const handleCallback = useCallback(async (code: string, state: string) => {
    try {
      setIsProcessing(true)
      setError(null)

      const response = await authAPI.handleGoogleOIDCCallback(
        code, 
        state, 
        redirectUrl
      )

      if (response.user && response.access_token) {
        // Store access token
        tokenManager.setToken(response.access_token)
        
        // Success - the calling component should handle navigation
        return response
      } else {
        throw new Error('Invalid response from Google OIDC callback')
      }
    } catch (err) {
      const errorMessage = getErrorMessage(err)
      setError(errorMessage)
      throw err
    } finally {
      setIsProcessing(false)
    }
  }, [redirectUrl])

  // Clear error state
  const clearError = useCallback(() => {
    setError(null)
  }, [])

  return {
    isProcessing,
    error,
    redirectUrl,
    initiateLogin,
    handleCallback,
    clearError,
  }
}