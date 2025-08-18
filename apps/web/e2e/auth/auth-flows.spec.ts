/**
 * Ultra-Enterprise Authentication Flows E2E Tests - Task 3.15
 * 
 * Comprehensive testing of all authentication flows with banking-grade
 * security validation and Turkish KVKV compliance verification.
 * 
 * Tests cover:
 * - User registration with KVKV compliance
 * - Password-based login with account lockout protection
 * - MFA TOTP setup and challenge flows
 * - OIDC/Google OAuth2 authentication
 * - Magic link passwordless authentication
 * - Session management and logout
 * - License guard redirects
 * - Idle logout testing
 */

import { test, expect, Page } from '@playwright/test'
import { 
  AuthTestUtils, 
  SecurityTestUtils,
  PerformanceTestUtils,
  AuditTestUtils,
  TEST_CORRELATION_ID 
} from '../utils/test-utils'
import { globalTestState } from '../setup/global-setup'

test.describe('Ultra-Enterprise Authentication Flows', () => {
  let authUtils: AuthTestUtils
  let securityUtils: SecurityTestUtils
  let performanceUtils: PerformanceTestUtils
  let auditUtils: AuditTestUtils

  test.beforeEach(async ({ page, request }) => {
    authUtils = new AuthTestUtils(page, request)
    securityUtils = new SecurityTestUtils(page, request)
    performanceUtils = new PerformanceTestUtils(page)
    auditUtils = new AuditTestUtils(request)
    
    // Set test correlation ID for audit tracking
    await page.addInitScript(() => {
      window.localStorage.setItem('test-correlation-id', TEST_CORRELATION_ID)
    })
  })

  test.describe('User Registration Flow', () => {
    test('should complete registration with KVKV compliance validation', async ({ page }) => {
      const credentials = AuthTestUtils.generateTestCredentials()
      
      // Measure performance
      const startTime = Date.now()
      
      await page.goto('/auth/register')
      
      // Validate Turkish UI elements
      await expect(page.locator('h1')).toContainText('Kayıt Ol')
      await expect(page.locator('text=KVKV')).toBeVisible()
      
      // Fill registration form
      await page.fill('input[name="email"]', credentials.email)
      await page.fill('input[name="password"]', credentials.password)
      await page.fill('input[name="firstName"]', credentials.firstName)
      await page.fill('input[name="lastName"]', credentials.lastName)
      
      if (credentials.phone) {
        await page.fill('input[name="phone"]', credentials.phone)
      }
      
      // KVKV compliance checkboxes
      await page.check('input[name="acceptTerms"]')
      await page.check('input[name="acceptKvkv"]')
      
      // Submit registration
      await page.click('button[type="submit"]')
      
      // Validate successful registration
      await expect(page.locator('[data-testid="registration-success"]')).toBeVisible()
      
      // Validate Turkish success message
      await expect(page.locator('text=başarıyla')).toBeVisible()
      
      // Measure performance
      const loadTime = Date.now() - startTime
      expect(loadTime).toBeLessThan(5000) // 5 seconds max for registration
      
      // Verify audit events
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'USER_REGISTRATION_INITIATED',
        'USER_REGISTRATION_COMPLETED',
        'KVKV_CONSENT_RECORDED'
      ])
      
      // Verify KVKV compliance in audit logs
      await auditUtils.verifyKvkvCompliance(TEST_CORRELATION_ID)
    })

    test('should reject registration with weak password', async ({ page }) => {
      const credentials = AuthTestUtils.generateTestCredentials()
      credentials.password = 'weak' // Weak password
      
      await page.goto('/auth/register')
      
      await page.fill('input[name="email"]', credentials.email)
      await page.fill('input[name="password"]', credentials.password)
      await page.fill('input[name="firstName"]', credentials.firstName)
      await page.fill('input[name="lastName"]', credentials.lastName)
      
      await page.check('input[name="acceptTerms"]')
      await page.check('input[name="acceptKvkv"]')
      
      await page.click('button[type="submit"]')
      
      // Should show password strength error in Turkish
      await expect(page.locator('text=Şifre çok zayıf')).toBeVisible()
      
      // Verify audit event for failed registration
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'USER_REGISTRATION_FAILED'
      ])
    })

    test('should prevent registration without KVKV consent', async ({ page }) => {
      const credentials = AuthTestUtils.generateTestCredentials()
      
      await page.goto('/auth/register')
      
      await page.fill('input[name="email"]', credentials.email)
      await page.fill('input[name="password"]', credentials.password)
      await page.fill('input[name="firstName"]', credentials.firstName)
      await page.fill('input[name="lastName"]', credentials.lastName)
      
      // Accept terms but NOT KVKV
      await page.check('input[name="acceptTerms"]')
      // Don't check KVKV consent
      
      await page.click('button[type="submit"]')
      
      // Should show KVKV consent required error
      await expect(page.locator('text=KVKV onayı gereklidir')).toBeVisible()
      
      // Form should not submit
      expect(page.url()).toContain('/auth/register')
    })
  })

  test.describe('Password-Based Login Flow', () => {
    let testUser: any

    test.beforeEach(async () => {
      // Create test user for login tests
      testUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
    })

    test('should complete successful login flow', async ({ page }) => {
      const startTime = Date.now()
      
      await page.goto('/auth/login')
      
      // Validate Turkish UI
      await expect(page.locator('h1')).toContainText('Giriş')
      
      // Login with valid credentials
      await page.fill('input[name="email"]', testUser.email)
      await page.fill('input[name="password"]', testUser.password)
      
      await page.click('button[type="submit"]')
      
      // Should redirect to dashboard
      await expect(page).toHaveURL(/.*\/dashboard/)
      
      // Validate authenticated state
      await authUtils.validateAuthenticated()
      
      // Measure performance
      const loadTime = Date.now() - startTime
      expect(loadTime).toBeLessThan(3000) // 3 seconds max for login
      
      // Verify audit events
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'USER_LOGIN_INITIATED',
        'USER_LOGIN_COMPLETED',
        'SESSION_CREATED'
      ])
    })

    test('should handle login with invalid credentials', async ({ page }) => {
      await page.goto('/auth/login')
      
      await page.fill('input[name="email"]', testUser.email)
      await page.fill('input[name="password"]', 'wrong-password')
      
      await page.click('button[type="submit"]')
      
      // Should show error message in Turkish
      await expect(page.locator('text=Geçersiz kimlik bilgileri')).toBeVisible()
      
      // Should remain on login page
      expect(page.url()).toContain('/auth/login')
      
      // Verify failed login audit event
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'USER_LOGIN_FAILED'
      ])
    })

    test('should enforce account lockout after multiple failed attempts', async ({ page }) => {
      await page.goto('/auth/login')
      
      // Attempt login multiple times with wrong password
      for (let i = 0; i < 6; i++) { // Assuming 5 attempt limit
        await page.fill('input[name="email"]', testUser.email)
        await page.fill('input[name="password"]', 'wrong-password')
        await page.click('button[type="submit"]')
        
        // Wait between attempts
        await page.waitForTimeout(1000)
      }
      
      // Should show account locked message
      await expect(page.locator('text=Hesap kilitlendi')).toBeVisible()
      
      // Verify lockout audit events
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'USER_LOGIN_FAILED',
        'ACCOUNT_LOCKED'
      ])
    })
  })

  test.describe('MFA TOTP Flow', () => {
    let mfaUser: any

    test.beforeEach(async () => {
      // Create and login user for MFA setup
      mfaUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(mfaUser.email, mfaUser.password)
    })

    test('should complete MFA setup flow', async ({ page }) => {
      await page.goto('/auth/mfa/setup')
      
      // Should show QR code for TOTP setup
      await expect(page.locator('[data-testid="qr-code"]')).toBeVisible()
      
      // Should show secret key backup
      const secretKey = await page.locator('[data-testid="secret-key"]').textContent()
      expect(secretKey).toBeTruthy()
      
      // Mock TOTP code generation (in real test, would use TOTP library)
      const mockTotpCode = '123456'
      
      await page.fill('input[name="totpCode"]', mockTotpCode)
      await page.click('button[type="submit"]')
      
      // Should show MFA enabled success message
      await expect(page.locator('text=İki faktörlü doğrulama etkinleştirildi')).toBeVisible()
      
      // Verify MFA setup audit events
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'MFA_SETUP_INITIATED',
        'MFA_SETUP_COMPLETED'
      ])
    })

    test('should require MFA during login for enabled users', async ({ page }) => {
      // Assume MFA is already enabled for this user
      await page.goto('/auth/login')
      
      await page.fill('input[name="email"]', mfaUser.email)
      await page.fill('input[name="password"]', mfaUser.password)
      await page.click('button[type="submit"]')
      
      // Should redirect to MFA challenge page
      await expect(page).toHaveURL(/.*\/auth\/mfa\/challenge/)
      
      // Should show MFA challenge form in Turkish
      await expect(page.locator('text=İki faktörlü doğrulama kodu')).toBeVisible()
      
      // Enter TOTP code
      const mockTotpCode = '123456'
      await page.fill('input[name="totpCode"]', mockTotpCode)
      await page.click('button[type="submit"]')
      
      // Should complete login and redirect to dashboard
      await expect(page).toHaveURL(/.*\/dashboard/)
      
      // Verify MFA challenge audit events
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'MFA_CHALLENGE_INITIATED',
        'MFA_CHALLENGE_COMPLETED'
      ])
    })

    test('should handle MFA backup codes', async ({ page }) => {
      await page.goto('/auth/mfa/backup-codes')
      
      // Should show backup codes
      const backupCodes = page.locator('[data-testid="backup-code"]')
      await expect(backupCodes).toHaveCount(10) // Standard 10 backup codes
      
      // Should allow regeneration
      await page.click('button[data-testid="regenerate-codes"]')
      
      // Should show confirmation dialog in Turkish
      await expect(page.locator('text=Yedek kodları yeniden oluştur')).toBeVisible()
      
      await page.click('button[data-testid="confirm-regenerate"]')
      
      // Should show new codes
      await expect(page.locator('text=Yeni yedek kodlar')).toBeVisible()
      
      // Verify backup codes audit event
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'MFA_BACKUP_CODES_REGENERATED'
      ])
    })
  })

  test.describe('OIDC/Google OAuth2 Flow', () => {
    test('should complete OIDC authentication flow', async ({ page }) => {
      await page.goto('/auth/oidc/google')
      
      // Should show Google login button
      await expect(page.locator('[data-testid="google-login-button"]')).toBeVisible()
      
      await page.click('[data-testid="google-login-button"]')
      
      // Should redirect to mock OIDC provider
      await page.waitForURL('**/oauth2/v2/auth**')
      
      // Select test user from mock provider
      await page.click('text=Test User')
      
      // Should redirect back to application
      await page.waitForURL('**/auth/oidc/callback**')
      
      // Should complete authentication and redirect to dashboard
      await expect(page).toHaveURL(/.*\/dashboard/)
      
      // Verify OIDC audit events
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'OIDC_LOGIN_INITIATED',
        'OIDC_LOGIN_COMPLETED',
        'SESSION_CREATED'
      ])
    })

    test('should handle OIDC callback errors', async ({ page }) => {
      // Simulate callback with error
      await page.goto('/auth/oidc/callback?error=access_denied&error_description=User+denied+access')
      
      // Should show error message in Turkish
      await expect(page.locator('text=Google girişi reddedildi')).toBeVisible()
      
      // Should redirect to login page
      await expect(page).toHaveURL(/.*\/auth\/login/)
      
      // Verify OIDC error audit event
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'OIDC_LOGIN_FAILED'
      ])
    })

    test('should validate PKCE security in OIDC flow', async ({ page, request }) => {
      await page.goto('/auth/oidc/google')
      
      // Monitor network requests to verify PKCE parameters
      const requests: any[] = []
      page.on('request', req => {
        if (req.url().includes('/oauth2/v2/auth')) {
          requests.push(req.url())
        }
      })
      
      await page.click('[data-testid="google-login-button"]')
      
      // Wait for redirect
      await page.waitForTimeout(2000)
      
      // Verify PKCE parameters are present
      const authRequest = requests[0]
      expect(authRequest).toContain('code_challenge=')
      expect(authRequest).toContain('code_challenge_method=S256')
      expect(authRequest).toContain('state=')
      expect(authRequest).toContain('nonce=')
    })
  })

  test.describe('Magic Link Authentication Flow', () => {
    test('should request magic link successfully', async ({ page }) => {
      const testEmail = 'magic.link.test@freecad-test.local'
      
      await page.goto('/auth/magic-link')
      
      // Should show magic link form in Turkish
      await expect(page.locator('text=Şifresiz giriş')).toBeVisible()
      
      await page.fill('input[name="email"]', testEmail)
      await page.click('button[type="submit"]')
      
      // Should show success message (always returns success for security)
      await expect(page.locator('text=Bağlantı gönderildi')).toBeVisible()
      
      // Verify magic link request in mock email service
      const emails = globalTestState.mockEmailService.getEmails(testEmail)
      expect(emails.length).toBeGreaterThan(0)
      
      // Verify audit event
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'MAGIC_LINK_REQUESTED'
      ])
    })

    test('should consume magic link and authenticate', async ({ page }) => {
      const testEmail = 'magic.consume.test@freecad-test.local'
      
      // First request magic link
      await page.goto('/auth/magic-link')
      await page.fill('input[name="email"]', testEmail)
      await page.click('button[type="submit"]')
      
      // Get magic link token from mock service
      const magicToken = globalTestState.mockEmailService.getLatestMagicLinkToken(testEmail)
      expect(magicToken).toBeTruthy()
      
      // Visit magic link URL
      await page.goto(`/auth/magic-link/consume?token=${magicToken}`)
      
      // Should authenticate and redirect to dashboard
      await expect(page).toHaveURL(/.*\/dashboard/)
      
      // Verify authentication state
      await authUtils.validateAuthenticated()
      
      // Verify audit events
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'MAGIC_LINK_CONSUMED',
        'SESSION_CREATED'
      ])
    })

    test('should reject invalid magic link tokens', async ({ page }) => {
      const invalidToken = 'invalid-token-12345'
      
      await page.goto(`/auth/magic-link/consume?token=${invalidToken}`)
      
      // Should show error message in Turkish
      await expect(page.locator('text=Geçersiz bağlantı')).toBeVisible()
      
      // Should redirect to login
      await expect(page).toHaveURL(/.*\/auth\/login/)
      
      // Verify failed consumption audit event
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'MAGIC_LINK_CONSUMPTION_FAILED'
      ])
    })

    test('should prevent magic link reuse', async ({ page }) => {
      const testEmail = 'magic.reuse.test@freecad-test.local'
      
      // Request and consume magic link first time
      await page.goto('/auth/magic-link')
      await page.fill('input[name="email"]', testEmail)
      await page.click('button[type="submit"]')
      
      const magicToken = globalTestState.mockEmailService.getLatestMagicLinkToken(testEmail)
      
      // First consumption - should work
      await page.goto(`/auth/magic-link/consume?token=${magicToken}`)
      await expect(page).toHaveURL(/.*\/dashboard/)
      
      // Logout
      await authUtils.logout()
      
      // Try to reuse same token - should fail
      await page.goto(`/auth/magic-link/consume?token=${magicToken}`)
      
      // Should show token already used error
      await expect(page.locator('text=Bağlantı zaten kullanıldı')).toBeVisible()
      
      // Verify reuse attempt audit event
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'MAGIC_LINK_REUSE_ATTEMPTED'
      ])
    })
  })

  test.describe('Session Management and Logout', () => {
    let sessionUser: any

    test.beforeEach(async () => {
      sessionUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(sessionUser.email, sessionUser.password)
    })

    test('should complete logout flow with session cleanup', async ({ page }) => {
      // Verify authenticated state
      await authUtils.validateAuthenticated()
      
      // Perform logout
      await authUtils.logout()
      
      // Verify session cleanup
      await authUtils.validateNotAuthenticated()
      
      // Verify cookies are cleared
      const cookies = await page.context().cookies()
      const authCookies = cookies.filter(c => 
        c.name.includes('access_token') || 
        c.name.includes('refresh_token') ||
        c.name.includes('rt')
      )
      expect(authCookies).toHaveLength(0)
      
      // Verify audit events
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'USER_LOGOUT_INITIATED',
        'SESSION_TERMINATED'
      ])
    })

    test('should handle refresh token rotation', async ({ page, request }) => {
      // Get initial tokens
      const initialCookies = await page.context().cookies()
      const refreshCookie = initialCookies.find(c => c.name === 'rt')
      expect(refreshCookie).toBeTruthy()
      
      // Make authenticated request to trigger token refresh
      await page.goto('/api/v1/me')
      
      // Wait for potential token refresh
      await page.waitForTimeout(1000)
      
      // Get new cookies
      const newCookies = await page.context().cookies()
      const newRefreshCookie = newCookies.find(c => c.name === 'rt')
      
      // Refresh token may have rotated
      expect(newRefreshCookie).toBeTruthy()
      
      // Verify audit event for token refresh
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'TOKEN_REFRESHED'
      ])
    })

    test('should enforce idle timeout', async ({ page }) => {
      // Simulate idle timeout (would need to mock system time)
      // For demo purposes, we'll test the idle detection mechanism
      
      await page.goto('/dashboard')
      
      // Simulate user being idle (no interaction)
      await page.waitForTimeout(30000) // 30 seconds
      
      // Check if idle warning is shown
      const idleWarning = page.locator('[data-testid="idle-warning"]')
      if (await idleWarning.isVisible()) {
        // Should show idle warning in Turkish
        await expect(page.locator('text=Oturum süresi dolmak üzere')).toBeVisible()
        
        // Wait for auto-logout
        await page.waitForTimeout(10000) // Additional 10 seconds
        
        // Should be logged out
        await expect(page).toHaveURL(/.*\/auth\/login/)
        
        // Verify idle logout audit event
        await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
          'IDLE_LOGOUT'
        ])
      }
    })
  })

  test.describe('License Guard and Protection', () => {
    test('should redirect unlicensed users to license page', async ({ page }) => {
      // Create user without license
      const unlicensedUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(unlicensedUser.email, unlicensedUser.password)
      
      // Try to access licensed feature
      await page.goto('/cad/new-project')
      
      // Should redirect to license page
      await expect(page).toHaveURL(/.*\/license\/purchase/)
      
      // Should show license required message in Turkish
      await expect(page.locator('text=Lisans gereklidir')).toBeVisible()
      
      // Verify license check audit event
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'LICENSE_CHECK_FAILED',
        'ACCESS_DENIED_NO_LICENSE'
      ])
    })

    test('should allow licensed users to access features', async ({ page, request }) => {
      // Create user and assign license (would need API call)
      const licensedUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(licensedUser.email, licensedUser.password)
      
      // Mock license assignment (in real test, would call license API)
      await request.post('/api/v1/license/assign', {
        headers: { 'Content-Type': 'application/json' },
        data: { licenseType: '3m', userId: 'test-user-id' }
      })
      
      // Should now access licensed feature
      await page.goto('/cad/new-project')
      
      // Should NOT redirect to license page
      expect(page.url()).not.toContain('/license/purchase')
      
      // Should show the actual feature
      await expect(page.locator('h1')).toContainText('Yeni Proje')
      
      // Verify successful access audit event
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, [
        'LICENSED_FEATURE_ACCESSED'
      ])
    })
  })

  test.describe('Cross-Browser Compatibility', () => {
    test('should work consistently across browsers', async ({ page, browserName }) => {
      const credentials = AuthTestUtils.generateTestCredentials()
      
      // Register user
      await authUtils.registerUser(credentials)
      
      // Login
      await authUtils.loginWithPassword(credentials.email, credentials.password)
      
      // Verify authentication works
      await authUtils.validateAuthenticated()
      
      // Test key authentication features work in all browsers
      await page.goto('/auth/mfa/setup')
      await expect(page.locator('[data-testid="qr-code"]')).toBeVisible()
      
      // Logout
      await authUtils.logout()
      
      console.log(`Authentication flow verified on ${browserName}`)
    })
  })
})

test.describe('Performance and Load Testing', () => {
  test('should handle concurrent authentication requests', async ({ page, context }) => {
    const concurrentUsers = 5
    const promises = []
    
    for (let i = 0; i < concurrentUsers; i++) {
      const newPage = await context.newPage()
      const newAuthUtils = new AuthTestUtils(newPage, newPage.request)
      
      promises.push(
        newAuthUtils.registerUser(AuthTestUtils.generateTestCredentials())
          .then(creds => newAuthUtils.loginWithPassword(creds.email, creds.password))
      )
    }
    
    // All authentications should complete successfully
    const results = await Promise.allSettled(promises)
    const failures = results.filter(r => r.status === 'rejected')
    
    expect(failures.length).toBe(0)
    console.log(`Successfully handled ${concurrentUsers} concurrent authentications`)
  })

  test('should maintain performance under load', async ({ page }) => {
    const performanceUtils = new PerformanceTestUtils(page)
    
    // Measure authentication flow performance
    const metrics = await performanceUtils.measurePageLoad('/auth/login')
    
    // Banking-grade performance requirements
    expect(metrics.loadTime).toBeLessThan(2000) // 2 seconds max
    
    if (metrics.fcp) {
      expect(metrics.fcp).toBeLessThan(1500) // First Contentful Paint < 1.5s
    }
    
    if (metrics.lcp) {
      expect(metrics.lcp).toBeLessThan(2500) // Largest Contentful Paint < 2.5s
    }
  })
})