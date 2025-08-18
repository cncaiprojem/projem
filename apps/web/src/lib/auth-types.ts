/**
 * TypeScript types and Zod validation schemas for authentication
 * Ultra-enterprise type safety and validation
 */

import { z } from 'zod'

// Form validation schemas with Turkish error messages
export const loginSchema = z.object({
  email: z
    .string()
    .min(1, 'E-posta adresi gereklidir')
    .email('Geçerli bir e-posta adresi girin')
    .max(100, 'E-posta adresi çok uzun'),
  password: z
    .string()
    .min(1, 'Şifre gereklidir')
    .min(8, 'Şifre en az 8 karakter olmalıdır')
    .max(128, 'Şifre çok uzun'),
})

export const registerSchema = z.object({
  firstName: z
    .string()
    .min(1, 'Ad gereklidir')
    .min(2, 'Ad en az 2 karakter olmalıdır')
    .max(50, 'Ad çok uzun')
    .regex(/^[a-zA-ZçğıöşüÇĞIÖŞÜ\s]+$/, 'Ad sadece harf içermelidir'),
  lastName: z
    .string()
    .min(1, 'Soyad gereklidir')
    .min(2, 'Soyad en az 2 karakter olmalıdır')
    .max(50, 'Soyad çok uzun')
    .regex(/^[a-zA-ZçğıöşüÇĞIÖŞÜ\s]+$/, 'Soyad sadece harf içermelidir'),
  email: z
    .string()
    .min(1, 'E-posta adresi gereklidir')
    .email('Geçerli bir e-posta adresi girin')
    .max(100, 'E-posta adresi çok uzun'),
  password: z
    .string()
    .min(8, 'Şifre en az 8 karakter olmalıdır')
    .max(128, 'Şifre çok uzun')
    .regex(
      /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]/,
      'Şifre en az bir büyük harf, küçük harf, sayı ve özel karakter içermelidir'
    ),
  confirmPassword: z
    .string()
    .min(1, 'Şifre tekrarı gereklidir'),
  company: z
    .string()
    .max(100, 'Şirket adı çok uzun')
    .optional(),
  acceptTerms: z
    .boolean()
    .refine((val) => val === true, 'Kullanım koşullarını kabul etmelisiniz'),
  acceptKvkk: z
    .boolean()
    .refine((val) => val === true, 'KVKV kapsamında veri işleme iznini vermelisiniz'),
}).refine((data) => data.password === data.confirmPassword, {
  message: 'Şifreler eşleşmiyor',
  path: ['confirmPassword'],
})

export const magicLinkRequestSchema = z.object({
  email: z
    .string()
    .min(1, 'E-posta adresi gereklidir')
    .email('Geçerli bir e-posta adresi girin')
    .max(100, 'E-posta adresi çok uzun'),
})

export const magicLinkConsumeSchema = z.object({
  token: z
    .string()
    .min(1, 'Token gereklidir'),
  email: z
    .string()
    .email('Geçerli bir e-posta adresi girin')
    .optional(),
})

// Type inference from schemas
export type LoginFormData = z.infer<typeof loginSchema>
export type RegisterFormData = z.infer<typeof registerSchema>
export type MagicLinkRequestData = z.infer<typeof magicLinkRequestSchema>
export type MagicLinkConsumeData = z.infer<typeof magicLinkConsumeSchema>

// User-related types
export interface User {
  id: string
  email: string
  firstName: string
  lastName: string
  company?: string
  isVerified: boolean
  role: string
  createdAt: string
  updatedAt: string
  lastLoginAt?: string
}

export interface SessionInfo {
  user: User
  expiresAt: string
  isAuthenticated: boolean
  sessionId: string
}

// Authentication state types
export interface AuthState {
  isAuthenticated: boolean
  isLoading: boolean
  user: User | null
  error: string | null
  sessionInfo: SessionInfo | null
}

// Form states
export interface FormState {
  isSubmitting: boolean
  error: string | null
  success: string | null
}

// OAuth types
export interface GoogleOIDCState {
  isProcessing: boolean
  error: string | null
  redirectUrl?: string
}

// Magic Link types
export interface MagicLinkState {
  isRequesting: boolean
  isConsuming: boolean
  emailSent: boolean
  sentToEmail: string | null
  error: string | null
  success: string | null
}

// Password strength types
export enum PasswordStrength {
  VeryWeak = 'very-weak',
  Weak = 'weak',
  Fair = 'fair',
  Strong = 'strong',
  VeryStrong = 'very-strong',
}

export interface PasswordStrengthResult {
  strength: PasswordStrength
  score: number // 0-100
  feedback: string[]
  isValid: boolean
}

// Error types with Turkish localization support
export interface LocalizedError {
  code: string
  message: string
  turkishMessage?: string
  field?: string
  details?: Record<string, unknown>
}

// Authentication event types
export enum AuthEventType {
  Login = 'login',
  Logout = 'logout',
  Register = 'register',
  GoogleOIDC = 'google-oidc',
  MagicLink = 'magic-link',
  SessionExpired = 'session-expired',
  SessionExtended = 'session-extended',
  TokenRefresh = 'token-refresh',
}

export interface AuthEvent {
  type: AuthEventType
  timestamp: number
  userId?: string
  sessionId?: string
  details?: Record<string, unknown>
}

// Rate limiting types
export interface RateLimitInfo {
  remaining: number
  reset: number
  limit: number
  isLimited: boolean
}

// Security compliance types (Turkish KVKK)
export interface KvkvConsent {
  acceptedAt: string
  ipAddress: string
  userAgent: string
  version: string
  isActive: boolean
}

export interface TermsAcceptance {
  acceptedAt: string
  version: string
  ipAddress: string
  isActive: boolean
}

export interface ComplianceInfo {
  kvkv: KvkvConsent
  terms: TermsAcceptance
  dataRetentionDays: number
  lastUpdated: string
}

// Response types that match backend API
export interface AuthResponse {
  access_token?: string
  user?: User
  message?: string
  requiresVerification?: boolean
  sessionInfo?: SessionInfo
  complianceInfo?: ComplianceInfo
}

// Hook return types
export interface UseAuthReturn extends AuthState {
  login: (credentials: LoginFormData) => Promise<void>
  register: (userData: RegisterFormData) => Promise<void>
  logout: () => Promise<void>
  refreshToken: () => Promise<void>
  extendSession: () => Promise<void>
  clearError: () => void
}

export interface UseGoogleOIDCReturn extends GoogleOIDCState {
  initiateLogin: (redirectUrl?: string) => Promise<void>
  handleCallback: (code: string, state: string) => Promise<void>
  clearError: () => void
}

export interface UseMagicLinkReturn extends MagicLinkState {
  requestMagicLink: (email: string) => Promise<void>
  consumeMagicLink: (token: string, email?: string) => Promise<void>
  resendMagicLink: () => Promise<void>
  clearState: () => void
}

// Validation utility types
export type ValidationError = {
  field: string
  message: string
}

export type ValidationResult = {
  isValid: boolean
  errors: ValidationError[]
}

// Form component prop types
export interface BaseFormProps {
  onSubmit: (data: any) => Promise<void>
  isLoading?: boolean
  error?: string | null
  success?: string | null
  className?: string
}

export interface LoginFormProps extends BaseFormProps {
  onSubmit: (data: LoginFormData) => Promise<void>
  onForgotPassword?: () => void
  onCreateAccount?: () => void
  showMagicLink?: boolean
  showGoogleOIDC?: boolean
}

export interface RegisterFormProps extends BaseFormProps {
  onSubmit: (data: RegisterFormData) => Promise<void>
  onSignIn?: () => void
  showGoogleOIDC?: boolean
}

export interface MagicLinkFormProps extends BaseFormProps {
  onSubmit: (data: MagicLinkRequestData) => Promise<void>
  onBackToLogin?: () => void
  sentToEmail?: string | null
  showResend?: boolean
  onResend?: () => Promise<void>
}

// Layout and styling types
export interface AuthLayoutProps {
  children: React.ReactNode
  title: string
  subtitle?: string
  showLanguageSwitch?: boolean
  showSecurityNotice?: boolean
  className?: string
}

export interface SecurityNoticeProps {
  showKvkk?: boolean
  showDataEncryption?: boolean
  className?: string
}

// URL and navigation types
export interface AuthRedirectInfo {
  from?: string
  to?: string
  reason?: 'login' | 'logout' | 'session_expired' | 'unauthorized'
}

// Configuration types
export interface AuthConfig {
  apiBaseUrl: string
  enableDevMode: boolean
  sessionTimeout: number
  csrfRefreshInterval: number
  passwordStrengthMinScore: number
  enableGoogleOIDC: boolean
  enableMagicLink: boolean
  enableRememberMe: boolean
  defaultLanguage: 'tr' | 'en'
  supportedLanguages: string[]
}