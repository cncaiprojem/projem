/**
 * Ultra-Enterprise Authentication API Client
 * Implements CSRF protection, secure token management, and Turkish error handling
 * Integrates with Tasks 3.1, 3.3, 3.5, 3.6, 3.8 backend implementation
 */

import { API_BASE } from './api'

// TypeScript interfaces for type safety
export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
  firstName: string
  lastName: string
  company?: string
  acceptTerms: boolean
  acceptKvkk: boolean
}

export interface MagicLinkRequest {
  email: string
}

export interface MagicLinkConsumeRequest {
  token: string
  email?: string
}

export interface AuthResponse {
  access_token?: string
  user?: {
    id: string
    email: string
    firstName: string
    lastName: string
    company?: string
    isVerified: boolean
    role: string
  }
  message?: string
  requiresVerification?: boolean
}

export interface LicenseStatusResponse {
  status: 'active' | 'expired' | 'suspended' | 'trial' | 'none'
  days_remaining: number
  expires_at: string
  plan_type: string
  seats_total: number
  seats_used: number
  features: Record<string, any>
  auto_renew: boolean
  status_tr: string
  warning_message_tr?: string
  renewal_url?: string
}

export interface LicenseFeatureCheckRequest {
  feature: string
}

export interface LicenseFeatureCheckResponse {
  feature: string
  available: boolean
  limit?: number
  current_usage?: number
}

export interface CSRFTokenResponse {
  csrf_token: string
}

export interface AuthError {
  code: string
  message: string
  field?: string
  remaining_attempts?: number
  lockout_duration?: number
}

// CSRF token management
class CSRFManager {
  private static instance: CSRFManager
  private csrfToken: string | null = null
  private lastFetch: number = 0
  private readonly REFRESH_INTERVAL = 30 * 60 * 1000 // 30 minutes

  static getInstance(): CSRFManager {
    if (!CSRFManager.instance) {
      CSRFManager.instance = new CSRFManager()
    }
    return CSRFManager.instance
  }

  async getToken(): Promise<string | null> {
    const now = Date.now()
    
    // Refresh token if it's older than 30 minutes or doesn't exist
    if (!this.csrfToken || (now - this.lastFetch) > this.REFRESH_INTERVAL) {
      try {
        const response = await fetch(`${API_BASE}/api/v1/auth/csrf-token`, {
          method: 'GET',
          credentials: 'include', // Include cookies for CSRF
          cache: 'no-store',
        })

        if (response.ok) {
          const data: CSRFTokenResponse = await response.json()
          this.csrfToken = data.csrf_token
          this.lastFetch = now
        } else {
          console.warn('Failed to fetch CSRF token:', response.status)
          return null
        }
      } catch (error) {
        console.error('Error fetching CSRF token:', error)
        return null
      }
    }

    return this.csrfToken
  }

  clearToken(): void {
    this.csrfToken = null
    this.lastFetch = 0
  }
}

// Enhanced API client with security features
class AuthAPI {
  private csrfManager = CSRFManager.getInstance()

  private async makeAuthenticatedRequest<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const csrfToken = await this.csrfManager.getToken()
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(csrfToken && { 'X-CSRF-Token': csrfToken }),
      ...(options.headers as Record<string, string>),
    }

    const response = await fetch(`${API_BASE}${endpoint}`, {
      ...options,
      headers,
      credentials: 'include', // Include cookies for session management
      cache: 'no-store',
    })

    if (response.status === 403) {
      // CSRF token might be expired, clear and retry once
      if (csrfToken) {
        this.csrfManager.clearToken()
        const newToken = await this.csrfManager.getToken()
        if (newToken && newToken !== csrfToken) {
          headers['X-CSRF-Token'] = newToken
          const retryResponse = await fetch(`${API_BASE}${endpoint}`, {
            ...options,
            headers,
            credentials: 'include',
            cache: 'no-store',
          })
          return this.handleResponse<T>(retryResponse)
        }
      }
    }

    return this.handleResponse<T>(response)
  }

  private async handleResponse<T>(response: Response): Promise<T> {
    const responseText = await response.text()
    
    if (!response.ok) {
      let errorData: AuthError
      
      try {
        errorData = JSON.parse(responseText) as AuthError
      } catch {
        // Fallback error format
        errorData = {
          code: 'NETWORK_ERROR',
          message: responseText || `HTTP ${response.status}`,
        }
      }

      throw new AuthAPIError(
        errorData.message || 'An error occurred',
        errorData.code,
        response.status,
        errorData
      )
    }

    // Handle empty responses
    if (!responseText.trim()) {
      return {} as T
    }

    try {
      return JSON.parse(responseText) as T
    } catch {
      // Return text as is if it's not valid JSON
      return responseText as unknown as T
    }
  }

  // Authentication endpoints
  async login(credentials: LoginRequest): Promise<AuthResponse> {
    return this.makeAuthenticatedRequest<AuthResponse>('/api/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    })
  }

  async register(userData: RegisterRequest): Promise<AuthResponse> {
    return this.makeAuthenticatedRequest<AuthResponse>('/api/v1/auth/register', {
      method: 'POST',
      body: JSON.stringify(userData),
    })
  }

  async logout(): Promise<void> {
    try {
      await this.makeAuthenticatedRequest<void>('/api/v1/auth/logout', {
        method: 'POST',
      })
    } finally {
      // Always clear CSRF token on logout
      this.csrfManager.clearToken()
    }
  }

  async refreshToken(): Promise<AuthResponse> {
    return this.makeAuthenticatedRequest<AuthResponse>('/api/v1/auth/refresh', {
      method: 'POST',
    })
  }

  async getCurrentUser(): Promise<AuthResponse> {
    return this.makeAuthenticatedRequest<AuthResponse>('/api/v1/auth/me')
  }

  // Google OIDC endpoints
  async initiateGoogleOIDC(redirectUrl?: string): Promise<{ authorization_url: string }> {
    const params = new URLSearchParams()
    if (redirectUrl) {
      params.set('redirect_url', redirectUrl)
    }

    return this.makeAuthenticatedRequest<{ authorization_url: string }>(
      `/api/v1/auth/oidc/google/start?${params.toString()}`
    )
  }

  async handleGoogleOIDCCallback(
    code: string,
    state: string,
    redirectUrl?: string
  ): Promise<AuthResponse> {
    return this.makeAuthenticatedRequest<AuthResponse>('/api/v1/auth/oidc/google/callback', {
      method: 'POST',
      body: JSON.stringify({
        code,
        state,
        redirect_url: redirectUrl,
      }),
    })
  }

  // Magic Link endpoints
  async requestMagicLink(request: MagicLinkRequest): Promise<{ message: string }> {
    return this.makeAuthenticatedRequest<{ message: string }>('/api/v1/auth/magic-link/request', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  }

  async consumeMagicLink(request: MagicLinkConsumeRequest): Promise<AuthResponse> {
    return this.makeAuthenticatedRequest<AuthResponse>('/api/v1/auth/magic-link/consume', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  }

  // Session management
  async extendSession(): Promise<{ expires_at: string }> {
    return this.makeAuthenticatedRequest<{ expires_at: string }>('/api/v1/auth/session/extend', {
      method: 'POST',
    })
  }

  async getSessionInfo(): Promise<{
    user: AuthResponse['user']
    expires_at: string
    is_authenticated: boolean
  }> {
    return this.makeAuthenticatedRequest('/api/v1/auth/session')
  }

  // License management endpoints (Task 3.14)
  async getLicenseStatus(): Promise<LicenseStatusResponse> {
    return this.makeAuthenticatedRequest<LicenseStatusResponse>('/api/v1/license/me')
  }

  async checkFeatureAvailability(request: LicenseFeatureCheckRequest): Promise<LicenseFeatureCheckResponse> {
    return this.makeAuthenticatedRequest<LicenseFeatureCheckResponse>('/api/v1/license/check-feature', {
      method: 'POST',
      body: JSON.stringify(request),
    })
  }

  async getAdminLicenseList(): Promise<any[]> {
    return this.makeAuthenticatedRequest<any[]>('/api/v1/license/admin/all')
  }

  // Dev mode endpoints (only available in development)
  async devLogin(userEmail: string = 'dev@local'): Promise<AuthResponse> {
    if (process.env.NODE_ENV !== 'development') {
      throw new Error('Dev login is only available in development mode')
    }

    return fetch(`${API_BASE}/api/v1/auth/dev-login`, {
      method: 'POST',
      headers: {
        'X-Dev-User': userEmail,
        'Content-Type': 'application/json',
      },
      credentials: 'include',
    }).then(response => this.handleResponse<AuthResponse>(response))
  }
}

// Custom error class for better error handling
export class AuthAPIError extends Error {
  constructor(
    message: string,
    public code: string,
    public status: number,
    public details: AuthError
  ) {
    super(message)
    this.name = 'AuthAPIError'
  }

  get isNetworkError(): boolean {
    return this.code === 'NETWORK_ERROR' || this.status === 0
  }

  get isValidationError(): boolean {
    return this.status === 400 && (
      this.code === 'VALIDATION_ERROR' ||
      this.code === 'INVALID_CREDENTIALS' ||
      this.code === 'EMAIL_ALREADY_EXISTS'
    )
  }

  get isRateLimited(): boolean {
    return this.status === 429
  }

  get isUnauthorized(): boolean {
    return this.status === 401
  }

  get isForbidden(): boolean {
    return this.status === 403
  }

  get isCSRFError(): boolean {
    return this.status === 403 && this.code === 'CSRF_TOKEN_MISSING'
  }

  get requiresRetry(): boolean {
    return this.isNetworkError || this.status >= 500
  }

  // Helper to get Turkish error message
  getTurkishMessage(): string {
    const errorMessages: Record<string, string> = {
      'INVALID_CREDENTIALS': 'E-posta veya şifre hatalı',
      'EMAIL_ALREADY_EXISTS': 'Bu e-posta adresi zaten kullanılıyor',
      'ACCOUNT_NOT_FOUND': 'Bu e-posta adresine kayıtlı hesap bulunamadı',
      'ACCOUNT_LOCKED': 'Hesabınız güvenlik nedeniyle kilitlenmiştir',
      'TOO_MANY_ATTEMPTS': 'Çok fazla başarısız deneme. Lütfen bekleyin',
      'WEAK_PASSWORD': 'Şifre çok zayıf',
      'NETWORK_ERROR': 'Ağ hatası. İnternet bağlantınızı kontrol edin',
      'SESSION_EXPIRED': 'Oturumunuzun süresi dolmuş',
      'CSRF_TOKEN_MISSING': 'Güvenlik hatası. Sayfayı yenileyip tekrar deneyin',
      'MAGIC_LINK_EXPIRED': 'Bu link süresi dolmuş',
      'MAGIC_LINK_INVALID': 'Geçersiz veya kullanılmış link',
      'OAUTH_ERROR': 'Google ile giriş başarısız oldu',
      'SERVER_ERROR': 'Sunucu hatası. Lütfen daha sonra tekrar deneyin',
      
      // Task 3.14: License-related error messages in Turkish
      'LICENSE_NOT_FOUND': 'Aktif lisans bulunamadı',
      'LICENSE_EXPIRED': 'Lisansınızın süresi dolmuş',
      'LICENSE_SUSPENDED': 'Lisansınız askıya alınmış',
      'LICENSE_CHECK_FAILED': 'Lisans durumu kontrol edilemedi',
      'FEATURE_CHECK_FAILED': 'Özellik durumu kontrol edilemedi',
      'ADMIN_LICENSE_LIST_FAILED': 'Lisans listesi alınamadı',
      'INSUFFICIENT_LICENSE': 'Bu özellik için yüksek seviye lisans gerekiyor',
      'LICENSE_LIMIT_EXCEEDED': 'Lisans kullanım sınırı aşıldı',
      'FEATURE_NOT_AVAILABLE': 'Bu özellik lisansınızda bulunmuyor',
      'TRIAL_EXPIRED': 'Deneme süreniz dolmuş',
      'SEAT_LIMIT_EXCEEDED': 'Kullanıcı kotası aşıldı',
    }

    return errorMessages[this.code] || this.message
  }
}

// Export singleton instance
export const authAPI = new AuthAPI()

// Export utility functions
export const isDevMode = (): boolean => {
  return process.env.NODE_ENV === 'development' && 
         process.env.NEXT_PUBLIC_DEV_AUTH_BYPASS === 'true'
}

export const getErrorMessage = (error: unknown): string => {
  if (error instanceof AuthAPIError) {
    return error.getTurkishMessage()
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Beklenmeyen bir hata oluştu'
}

// Token storage in memory (never localStorage for security)
class TokenManager {
  private static instance: TokenManager
  private accessToken: string | null = null
  private tokenExpiry: number | null = null

  static getInstance(): TokenManager {
    if (!TokenManager.instance) {
      TokenManager.instance = new TokenManager()
    }
    return TokenManager.instance
  }

  setToken(token: string, expiresIn?: number): void {
    this.accessToken = token
    if (expiresIn) {
      this.tokenExpiry = Date.now() + (expiresIn * 1000) - 60000 // Refresh 1 minute early
    }
  }

  getToken(): string | null {
    if (this.tokenExpiry && Date.now() >= this.tokenExpiry) {
      this.clearToken()
      return null
    }
    return this.accessToken
  }

  clearToken(): void {
    this.accessToken = null
    this.tokenExpiry = null
  }

  isTokenExpiring(): boolean {
    if (!this.tokenExpiry) return false
    return Date.now() >= (this.tokenExpiry - 5 * 60 * 1000) // 5 minutes before expiry
  }
}

export const tokenManager = TokenManager.getInstance()