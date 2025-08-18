/**
 * Ultra-Enterprise Authentication Hook
 * Provides comprehensive auth state management with Turkish error handling
 */

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { authAPI, getErrorMessage, tokenManager } from '@/lib/auth-api'
import {
  UseAuthReturn,
  LoginFormData,
  RegisterFormData,
  User,
  SessionInfo,
} from '@/lib/auth-types'

const REFRESH_BUFFER = 5 * 60 * 1000 // 5 minutes before expiry
const CHECK_INTERVAL = 60 * 1000 // Check every minute

export function useAuth(): UseAuthReturn {
  const router = useRouter()
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const [user, setUser] = useState<User | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sessionInfo, setSessionInfo] = useState<SessionInfo | null>(null)

  // Initialize auth state
  const initializeAuth = useCallback(async () => {
    try {
      setIsLoading(true)
      const sessionResponse = await authAPI.getSessionInfo()
      
      if (sessionResponse.is_authenticated && sessionResponse.user) {
        setIsAuthenticated(true)
        setUser(sessionResponse.user)
        setSessionInfo(sessionResponse)
        
        // Set up token refresh if needed
        if (tokenManager.isTokenExpiring()) {
          await refreshToken()
        }
      } else {
        setIsAuthenticated(false)
        setUser(null)
        setSessionInfo(null)
      }
    } catch (err) {
      console.warn('Auth initialization failed:', err)
      setIsAuthenticated(false)
      setUser(null)
      setSessionInfo(null)
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Login function
  const login = useCallback(async (credentials: LoginFormData) => {
    try {
      setIsLoading(true)
      setError(null)

      const response = await authAPI.login(credentials)

      if (response.user && response.access_token) {
        tokenManager.setToken(response.access_token)
        setIsAuthenticated(true)
        setUser(response.user)
        
        // Fetch updated session info
        const sessionResponse = await authAPI.getSessionInfo()
        setSessionInfo(sessionResponse)
      }
    } catch (err) {
      const errorMessage = getErrorMessage(err)
      setError(errorMessage)
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Register function
  const register = useCallback(async (userData: RegisterFormData) => {
    try {
      setIsLoading(true)
      setError(null)

      const response = await authAPI.register(userData)

      if (response.user && response.access_token) {
        tokenManager.setToken(response.access_token)
        setIsAuthenticated(true)
        setUser(response.user)
        
        // Fetch updated session info
        const sessionResponse = await authAPI.getSessionInfo()
        setSessionInfo(sessionResponse)
      }
    } catch (err) {
      const errorMessage = getErrorMessage(err)
      setError(errorMessage)
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Logout function
  const logout = useCallback(async () => {
    try {
      setIsLoading(true)
      await authAPI.logout()
    } catch (err) {
      console.warn('Logout API call failed:', err)
    } finally {
      // Always clear local state
      tokenManager.clearToken()
      setIsAuthenticated(false)
      setUser(null)
      setSessionInfo(null)
      setError(null)
      setIsLoading(false)

      // Clear any dev auth flags
      if (typeof window !== 'undefined') {
        localStorage.removeItem('devAuthed')
      }

      // Redirect to login
      router.push('/login')
    }
  }, [router])

  // Refresh token function
  const refreshToken = useCallback(async () => {
    try {
      const response = await authAPI.refreshToken()
      
      if (response.access_token) {
        tokenManager.setToken(response.access_token)
      }
      
      if (response.user) {
        setUser(response.user)
      }

      // Update session info
      const sessionResponse = await authAPI.getSessionInfo()
      setSessionInfo(sessionResponse)
      
      return response
    } catch (err) {
      console.warn('Token refresh failed:', err)
      // Don't throw here - let the automatic retry handle it
      throw err
    }
  }, [])

  // Extend session function
  const extendSession = useCallback(async () => {
    try {
      const response = await authAPI.extendSession()
      
      // Update session info
      const sessionResponse = await authAPI.getSessionInfo()
      setSessionInfo(sessionResponse)
      
      return response
    } catch (err) {
      const errorMessage = getErrorMessage(err)
      setError(errorMessage)
      throw err
    }
  }, [])

  // Clear error function
  const clearError = useCallback(() => {
    setError(null)
  }, [])

  // Set up session monitoring
  useEffect(() => {
    let interval: NodeJS.Timeout

    if (isAuthenticated && sessionInfo) {
      interval = setInterval(async () => {
        try {
          // Check if token is expiring
          if (tokenManager.isTokenExpiring()) {
            await refreshToken()
          }
        } catch (err) {
          console.warn('Automatic token refresh failed:', err)
          // If refresh fails, user will need to re-authenticate
          await logout()
        }
      }, CHECK_INTERVAL)
    }

    return () => {
      if (interval) {
        clearInterval(interval)
      }
    }
  }, [isAuthenticated, sessionInfo, refreshToken, logout])

  // Initialize on mount
  useEffect(() => {
    initializeAuth()
  }, [initializeAuth])

  // Handle page visibility change to refresh session
  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && isAuthenticated) {
        // Re-check auth status when page becomes visible
        initializeAuth()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
  }, [isAuthenticated, initializeAuth])

  return {
    isAuthenticated,
    isLoading,
    user,
    error,
    sessionInfo,
    login,
    register,
    logout,
    refreshToken,
    extendSession,
    clearError,
  }
}