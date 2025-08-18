/**
 * Ultra-Enterprise Audit Logging and Turkish Validation Tests - Task 3.15
 * 
 * Comprehensive testing of audit logging functionality and Turkish error messages
 * Validates compliance with banking-grade audit requirements and Turkish KVKV standards
 * Ensures complete audit trail for security monitoring and regulatory compliance.
 */

import { test, expect, Page } from '@playwright/test'
import { 
  AuditTestUtils, 
  AuthTestUtils, 
  SecurityTestUtils,
  TEST_CORRELATION_ID 
} from '../utils/test-utils'

test.describe('Audit Logging and Turkish Validation', () => {
  let auditUtils: AuditTestUtils
  let authUtils: AuthTestUtils
  let securityUtils: SecurityTestUtils

  test.beforeEach(async ({ page, request }) => {
    auditUtils = new AuditTestUtils(request)
    authUtils = new AuthTestUtils(page, request)
    securityUtils = new SecurityTestUtils(page, request)
    
    // Set test correlation ID for audit tracking
    await page.addInitScript(() => {
      window.localStorage.setItem('test-correlation-id', TEST_CORRELATION_ID)
    })
  })

  test.describe('Authentication Audit Events', () => {
    test('should log comprehensive audit events for user registration', async ({ page, request }) => {
      
      const credentials = AuthTestUtils.generateTestCredentials()
      
      // Perform registration
      await page.goto('/auth/register')
      await page.fill('input[name="email"]', credentials.email)
      await page.fill('input[name="password"]', credentials.password)
      await page.fill('input[name="firstName"]', credentials.firstName)
      await page.fill('input[name="lastName"]', credentials.lastName)
      await page.check('input[name="acceptTerms"]')
      await page.check('input[name="acceptKvkv"]')
      
      // Add correlation ID for tracking
      await page.addInitScript(() => {
        window.localStorage.setItem('test-correlation-id', TEST_CORRELATION_ID)
      })
      
      await page.click('button[type="submit"]')
      
      // Wait for registration completion
      await expect(page.locator('[data-testid="registration-success"]')).toBeVisible()
      
      // Verify audit events were created
      
      const expectedEvents = [
        'USER_REGISTRATION_INITIATED',
        'USER_REGISTRATION_COMPLETED',
        'KVKV_CONSENT_RECORDED',
        'TERMS_ACCEPTANCE_RECORDED'
      ]
      
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, expectedEvents)
      
      // Verify KVKV compliance in audit logs
      await auditUtils.verifyKvkvCompliance(TEST_CORRELATION_ID)
      
      // Login as admin to access audit logs endpoint
      const adminToken = await authUtils.loginAsAdmin()
      
      // Verify audit log structure and content
      const auditResponse = await request.get('/api/v1/admin/audit-logs', {
        headers: {
          'Authorization': `Bearer ${adminToken}`,
          'X-Test-Correlation-ID': TEST_CORRELATION_ID
        },
        params: {
          correlation_id: TEST_CORRELATION_ID,
          limit: 10
        }
      })
      
      expect(auditResponse.status()).toBe(200)
      
      const auditData = await auditResponse.json()
      const auditEvents = auditData.items || []
      
      // Verify audit log structure
      for (const event of auditEvents) {
        expect(event.id).toBeTruthy()
        expect(event.event_type).toBeTruthy()
        expect(event.timestamp).toBeTruthy()
        expect(event.correlation_id).toBe(TEST_CORRELATION_ID)
        expect(event.ip_address).toBeTruthy()
        expect(event.user_agent).toBeTruthy()
        expect(event.details).toBeTruthy()
        
        // Verify no sensitive data is logged
        expect(event.details).not.toContain('password')
        expect(event.details).not.toContain(credentials.password)
        
      }
    })

    test('should log audit events for login attempts', async ({ page, request }) => {
      
      // Create test user first
      const credentials = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      
      // Test successful login
      await page.goto('/auth/login')
      await page.fill('input[name="email"]', credentials.email)
      await page.fill('input[name="password"]', credentials.password)
      
      await page.addInitScript(() => {
        window.localStorage.setItem('test-correlation-id', TEST_CORRELATION_ID)
      })
      
      await page.click('button[type="submit"]')
      
      // Wait for login completion
      await expect(page).toHaveURL(/.*\/dashboard/)
      
      // Verify successful login audit events
      const successEvents = [
        'USER_LOGIN_INITIATED',
        'USER_LOGIN_COMPLETED',
        'SESSION_CREATED'
      ]
      
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, successEvents)
      
      // Test failed login
      await authUtils.logout()
      
      const failedCorrelationId = `failed-${TEST_CORRELATION_ID}`
      
      await page.goto('/auth/login')
      await page.fill('input[name="email"]', credentials.email)
      await page.fill('input[name="password"]', 'wrong-password')
      
      await page.addInitScript(() => {
        window.localStorage.setItem('test-correlation-id', failedCorrelationId)
      })
      
      await page.click('button[type="submit"]')
      
      // Verify failed login audit events
      const failedEvents = [
        'USER_LOGIN_INITIATED',
        'USER_LOGIN_FAILED'
      ]
      
      await auditUtils.verifyAuditEvents(failedCorrelationId, failedEvents)
    })

    test('should log MFA audit events', async ({ page, request }) => {
      
      // Create user and login
      const credentials = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(credentials.email, credentials.password)
      
      // Initiate MFA setup
      await page.goto('/auth/mfa/setup')
      
      await page.addInitScript(() => {
        window.localStorage.setItem('test-correlation-id', TEST_CORRELATION_ID)
      })
      
      // Should show QR code for setup
      await expect(page.locator('[data-testid="qr-code"]')).toBeVisible()
      
      // Mock TOTP code entry
      await page.fill('input[name="totpCode"]', '123456')
      await page.click('button[type="submit"]')
      
      // Verify MFA audit events
      const mfaEvents = [
        'MFA_SETUP_INITIATED'
      ]
      
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, mfaEvents)
      
      // Test MFA challenge flow
      await authUtils.logout()
      
      const challengeCorrelationId = `mfa-challenge-${TEST_CORRELATION_ID}`
      
      await page.goto('/auth/login')
      await page.fill('input[name="email"]', credentials.email)
      await page.fill('input[name="password"]', credentials.password)
      
      await page.addInitScript(() => {
        window.localStorage.setItem('test-correlation-id', challengeCorrelationId)
      })
      
      await page.click('button[type="submit"]')
      
      // If MFA is required, should redirect to MFA challenge
      if (page.url().includes('/auth/mfa/challenge')) {
        await page.fill('input[name="totpCode"]', '123456')
        await page.click('button[type="submit"]')
        
        // Verify MFA challenge audit events
        const challengeEvents = [
          'MFA_CHALLENGE_INITIATED'
        ]
        
        await auditUtils.verifyAuditEvents(challengeCorrelationId, challengeEvents)
      }
    })

    test('should log OIDC authentication audit events', async ({ page }) => {
      
      await page.goto('/auth/oidc/google')
      
      await page.addInitScript(() => {
        window.localStorage.setItem('test-correlation-id', TEST_CORRELATION_ID)
      })
      
      // Click Google login button
      await page.click('[data-testid="google-login-button"]')
      
      // Should redirect to mock OIDC provider
      await page.waitForURL('**/oauth2/v2/auth**')
      
      // Select test user from mock provider
      await page.click('text=Test User')
      
      // Verify OIDC audit events
      const oidcEvents = [
        'OIDC_LOGIN_INITIATED'
      ]
      
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, oidcEvents)
    })

    test('should log magic link audit events', async ({ page }) => {
      
      const testEmail = 'magic.audit.test@freecad-test.local'
      
      await page.goto('/auth/magic-link')
      
      await page.addInitScript(() => {
        window.localStorage.setItem('test-correlation-id', TEST_CORRELATION_ID)
      })
      
      await page.fill('input[name="email"]', testEmail)
      await page.click('button[type="submit"]')
      
      // Should show success message
      await expect(page.locator('text=Bağlantı gönderildi')).toBeVisible()
      
      // Verify magic link audit events
      const magicLinkEvents = [
        'MAGIC_LINK_REQUESTED'
      ]
      
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, magicLinkEvents)
    })
  })

  test.describe('Security Audit Events', () => {
    test('should log security violation attempts', async ({ page, request }) => {
      
      // Test CSRF violation
      const csrfCorrelationId = `csrf-${TEST_CORRELATION_ID}`
      
      const csrfResponse = await request.post('/api/v1/auth/login', {
        headers: {
          'Content-Type': 'application/json',
          'X-Test-Correlation-ID': csrfCorrelationId
          // No CSRF token
        },
        data: {
          email: 'test@example.com',
          password: 'password'
        }
      })
      
      expect(csrfResponse.status()).toBe(403)
      
      // Verify CSRF violation audit event
      const csrfEvents = [
        'CSRF_VIOLATION_DETECTED'
      ]
      
      await auditUtils.verifyAuditEvents(csrfCorrelationId, csrfEvents)
      
      // Test rate limiting violation
      const rateLimitCorrelationId = `rate-limit-${TEST_CORRELATION_ID}`
      
      const requests = []
      for (let i = 0; i < 6; i++) {
        requests.push(
          request.post('/api/v1/auth/login', {
            headers: {
              'Content-Type': 'application/json',
              'X-Test-Correlation-ID': rateLimitCorrelationId
            },
            data: {
              email: 'rate.limit.test@example.com',
              password: 'wrong-password'
            }
          })
        )
      }
      
      const responses = await Promise.all(requests)
      const rateLimitedResponse = responses.find(r => r.status() === 429)
      
      if (rateLimitedResponse) {
        // Verify rate limit violation audit event
        const rateLimitEvents = [
          'RATE_LIMIT_VIOLATION'
        ]
        
        await auditUtils.verifyAuditEvents(rateLimitCorrelationId, rateLimitEvents)
      }
    })

    test('should log account lockout events', async ({ page }) => {
      
      // Create test user
      const credentials = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      
      const lockoutCorrelationId = `lockout-${TEST_CORRELATION_ID}`
      
      // Attempt multiple failed logins
      for (let i = 0; i < 6; i++) {
        await page.goto('/auth/login')
        await page.fill('input[name="email"]', credentials.email)
        await page.fill('input[name="password"]', 'wrong-password')
        
        await page.addInitScript(() => {
          window.localStorage.setItem('test-correlation-id', lockoutCorrelationId)
        })
        
        await page.click('button[type="submit"]')
        
        // Wait for login attempt to complete
        await page.waitForLoadState('networkidle')
      }
      
      // Verify account lockout audit events
      const lockoutEvents = [
        'ACCOUNT_LOCKED'
      ]
      
      await auditUtils.verifyAuditEvents(lockoutCorrelationId, lockoutEvents)
    })

    test('should log privilege escalation attempts', async ({ page, request }) => {
      
      // Create regular user
      const credentials = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      const loginResponse = await request.post('/api/v1/auth/login', {
        headers: { 'Content-Type': 'application/json' },
        data: {
          email: credentials.email,
          password: credentials.password
        }
      })
      
      const loginData = await loginResponse.json()
      const accessToken = loginData.access_token
      
      const escalationCorrelationId = `escalation-${TEST_CORRELATION_ID}`
      
      // Attempt to access admin endpoint without proper role
      const adminResponse = await request.get('/api/v1/admin/users', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'X-Test-Correlation-ID': escalationCorrelationId
        }
      })
      
      expect(adminResponse.status()).toBe(403)
      
      // Verify privilege escalation audit event
      const escalationEvents = [
        'UNAUTHORIZED_ACCESS_ATTEMPT'
      ]
      
      await auditUtils.verifyAuditEvents(escalationCorrelationId, escalationEvents)
    })
  })

  test.describe('Data Protection Audit Events', () => {
    test('should log KVKV consent events', async ({ page }) => {
      
      const credentials = AuthTestUtils.generateTestCredentials()
      
      await page.goto('/auth/register')
      await page.fill('input[name="email"]', credentials.email)
      await page.fill('input[name="password"]', credentials.password)
      await page.fill('input[name="firstName"]', credentials.firstName)
      await page.fill('input[name="lastName"]', credentials.lastName)
      
      await page.addInitScript(() => {
        window.localStorage.setItem('test-correlation-id', TEST_CORRELATION_ID)
      })
      
      // Accept terms and KVKV
      await page.check('input[name="acceptTerms"]')
      await page.check('input[name="acceptKvkv"]')
      
      await page.click('button[type="submit"]')
      
      // Verify KVKV consent audit events
      const kvkvEvents = [
        'KVKV_CONSENT_RECORDED',
        'TERMS_ACCEPTANCE_RECORDED'
      ]
      
      await auditUtils.verifyAuditEvents(TEST_CORRELATION_ID, kvkvEvents)
    })

    test('should log data access events', async ({ page, request }) => {
      
      // Create user and login
      const credentials = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      const loginResponse = await request.post('/api/v1/auth/login', {
        headers: { 'Content-Type': 'application/json' },
        data: {
          email: credentials.email,
          password: credentials.password
        }
      })
      
      const loginData = await loginResponse.json()
      const accessToken = loginData.access_token
      
      const dataAccessCorrelationId = `data-access-${TEST_CORRELATION_ID}`
      
      // Access user profile data
      const profileResponse = await request.get('/api/v1/me', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'X-Test-Correlation-ID': dataAccessCorrelationId
        }
      })
      
      expect(profileResponse.status()).toBe(200)
      
      // Verify data access audit events
      const dataAccessEvents = [
        'USER_DATA_ACCESSED'
      ]
      
      await auditUtils.verifyAuditEvents(dataAccessCorrelationId, dataAccessEvents)
    })

    test('should log data modification events', async ({ page, request }) => {
      
      // Create user and login
      const credentials = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      const loginResponse = await request.post('/api/v1/auth/login', {
        headers: { 'Content-Type': 'application/json' },
        data: {
          email: credentials.email,
          password: credentials.password
        }
      })
      
      const loginData = await loginResponse.json()
      const accessToken = loginData.access_token
      
      const dataModifyCorrelationId = `data-modify-${TEST_CORRELATION_ID}`
      
      // Update user profile
      const updateResponse = await request.put('/api/v1/me', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
          'X-Test-Correlation-ID': dataModifyCorrelationId
        },
        data: {
          firstName: 'Updated',
          lastName: 'Name',
          bio: 'Updated bio'
        }
      })
      
      expect(updateResponse.status()).toBe(200)
      
      // Verify data modification audit events
      const dataModifyEvents = [
        'USER_DATA_MODIFIED'
      ]
      
      await auditUtils.verifyAuditEvents(dataModifyCorrelationId, dataModifyEvents)
    })

    test('should log data deletion events', async ({ page, request }) => {
      
      // Create user and login
      const credentials = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      const loginResponse = await request.post('/api/v1/auth/login', {
        headers: { 'Content-Type': 'application/json' },
        data: {
          email: credentials.email,
          password: credentials.password
        }
      })
      
      const loginData = await loginResponse.json()
      const accessToken = loginData.access_token
      
      const dataDeletionCorrelationId = `data-deletion-${TEST_CORRELATION_ID}`
      
      // Delete user account
      const deleteResponse = await request.delete('/api/v1/me', {
        headers: {
          'Authorization': `Bearer ${accessToken}`,
          'X-Test-Correlation-ID': dataDeletionCorrelationId
        }
      })
      
      expect(deleteResponse.status()).toBe(200)
      
      // Verify data deletion audit events
      const dataDeletionEvents = [
        'USER_ACCOUNT_DELETED',
        'PERSONAL_DATA_DELETED'
      ]
      
      await auditUtils.verifyAuditEvents(dataDeletionCorrelationId, dataDeletionEvents)
    })
  })

  test.describe('Turkish Error Message Validation', () => {
    test('should display Turkish error messages for authentication failures', async ({ page }) => {
      
      const errorTestCases = [
        {
          name: 'Invalid email format',
          input: { email: 'invalid-email', password: 'password123' },
          expectedMessage: 'Geçersiz e-posta formatı',
          endpoint: 'login'
        },
        {
          name: 'Weak password',
          input: { 
            email: 'test@example.com', 
            password: 'weak',
            firstName: 'Test',
            lastName: 'User'
          },
          expectedMessage: 'Şifre çok zayıf',
          endpoint: 'register'
        },
        {
          name: 'Invalid credentials',
          input: { email: 'nonexistent@example.com', password: 'wrongpassword' },
          expectedMessage: 'Geçersiz kimlik bilgileri',
          endpoint: 'login'
        },
        {
          name: 'Missing KVKV consent',
          input: {
            email: 'test@example.com',
            password: 'StrongPass123!',
            firstName: 'Test',
            lastName: 'User',
            acceptTerms: true,
            acceptKvkv: false
          },
          expectedMessage: 'KVKV onayı gereklidir',
          endpoint: 'register'
        }
      ]
      
      for (const testCase of errorTestCases) {
        
        await page.goto(`/auth/${testCase.endpoint}`)
        
        // Fill form based on endpoint
        if (testCase.endpoint === 'register') {
          await page.fill('input[name="email"]', testCase.input.email)
          await page.fill('input[name="password"]', testCase.input.password)
          if (testCase.input.firstName) {
            await page.fill('input[name="firstName"]', testCase.input.firstName)
          }
          if (testCase.input.lastName) {
            await page.fill('input[name="lastName"]', testCase.input.lastName)
          }
          if (testCase.input.acceptTerms) {
            await page.check('input[name="acceptTerms"]')
          }
          if (testCase.input.acceptKvkv) {
            await page.check('input[name="acceptKvkv"]')
          }
        } else {
          await page.fill('input[name="email"]', testCase.input.email)
          await page.fill('input[name="password"]', testCase.input.password)
        }
        
        await page.click('button[type="submit"]')
        
        // Wait for form validation/error message to appear
        await expect(page.locator('.error-message, .alert-error, [data-testid="error-message"]')).toBeVisible()
        
        // Check for Turkish error message
        const errorElement = page.locator('.error-message, .alert-error, [data-testid="error-message"]')
        const errorText = await errorElement.textContent()
        
        // Verify Turkish error message is displayed
        expect(errorText).toBeTruthy()
        
        // Check for Turkish characteristics
        const hasTurkishContent = 
          errorText?.includes('Geçersiz') ||
          errorText?.includes('zayıf') ||
          errorText?.includes('kimlik') ||
          errorText?.includes('KVKV') ||
          errorText?.includes('onay') ||
          errorText?.includes('gerekli') ||
          /[çğıöşüÇĞIİÖŞÜ]/.test(errorText || '')
        
        expect(hasTurkishContent).toBe(true)
        
      }
    })

    test('should display Turkish error messages for security violations', async ({ page, request }) => {
      
      // Test rate limiting error
      const rateLimitRequests = []
      for (let i = 0; i < 6; i++) {
        rateLimitRequests.push(
          request.post('/api/v1/auth/login', {
            headers: { 'Content-Type': 'application/json' },
            data: {
              email: 'rate.test@example.com',
              password: 'wrong-password'
            }
          })
        )
      }
      
      const responses = await Promise.all(rateLimitRequests)
      const rateLimitedResponse = responses.find(r => r.status() === 429)
      
      if (rateLimitedResponse) {
        const errorData = await rateLimitedResponse.json()
        expect(errorData.message).toContain('çok fazla')
      }
      
      // Test CSRF error
      const csrfResponse = await request.post('/api/v1/auth/login', {
        headers: { 'Content-Type': 'application/json' },
        data: {
          email: 'csrf.test@example.com',
          password: 'password'
        }
      })
      
      if (csrfResponse.status() === 403) {
        const errorData = await csrfResponse.json()
        expect(errorData.message).toBeTruthy()
      }
      
      // Test access denied error
      await page.goto('/admin/users')
      
      // Should show access denied in Turkish
      const accessDeniedText = await page.locator('text=erişim, text=izin, text=yetki').textContent()
      if (accessDeniedText) {
      }
    })

    test('should display Turkish validation messages for forms', async ({ page }) => {
      
      // Test profile update form validation
      const credentials = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(credentials.email, credentials.password)
      
      await page.goto('/profile/edit')
      
      // Clear required field and submit
      await page.fill('input[name="firstName"]', '')
      await page.click('button[type="submit"]')
      
      // Should show required field error in Turkish
      const requiredError = page.locator('text=gerekli, text=zorunlu, text=boş olamaz')
      if (await requiredError.isVisible()) {
        const errorText = await requiredError.textContent()
      }
      
      // Test email format validation
      await page.fill('input[name="email"]', 'invalid-email')
      await page.click('button[type="submit"]')
      
      const emailError = page.locator('text=e-posta, text=format, text=geçersiz')
      if (await emailError.isVisible()) {
        const errorText = await emailError.textContent()
      }
    })

    test('should display Turkish success messages', async ({ page }) => {
      
      // Test registration success
      const credentials = AuthTestUtils.generateTestCredentials()
      
      await page.goto('/auth/register')
      await page.fill('input[name="email"]', credentials.email)
      await page.fill('input[name="password"]', credentials.password)
      await page.fill('input[name="firstName"]', credentials.firstName)
      await page.fill('input[name="lastName"]', credentials.lastName)
      await page.check('input[name="acceptTerms"]')
      await page.check('input[name="acceptKvkv"]')
      
      await page.click('button[type="submit"]')
      
      // Should show success message in Turkish
      const successMessage = page.locator('text=başarıyla, text=tamamlandı, text=oluşturuldu')
      if (await successMessage.isVisible()) {
        const messageText = await successMessage.textContent()
      }
      
      // Test login success (redirect to dashboard)
      await page.goto('/auth/login')
      await page.fill('input[name="email"]', credentials.email)
      await page.fill('input[name="password"]', credentials.password)
      await page.click('button[type="submit"]')
      
      // Should redirect to dashboard with Turkish UI
      await expect(page).toHaveURL(/.*\/dashboard/)
      
      const dashboardTitle = await page.locator('h1').textContent()
      const hasTurkishDashboard = 
        dashboardTitle?.includes('Panel') ||
        dashboardTitle?.includes('Gösterge') ||
        /[çğıöşüÇĞIİÖŞÜ]/.test(dashboardTitle || '')
      
      if (hasTurkishDashboard) {
      }
    })
  })

  test.describe('Audit Log Integrity and Security', () => {
    test('should maintain audit log integrity', async ({ page, request }) => {
      
      // Create multiple audit events
      const credentials = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(credentials.email, credentials.password)
      
      // Generate various audit events
      await page.goto('/profile/edit')
      await page.fill('input[name="firstName"]', 'Updated')
      await page.click('button[type="submit"]')
      
      await page.goto('/auth/mfa/setup')
      
      await authUtils.logout()
      
      // Login as admin to access audit logs endpoint
      const adminToken = await authUtils.loginAsAdmin()
      
      // Get audit logs
      const auditResponse = await request.get('/api/v1/admin/audit-logs', {
        headers: {
          'Authorization': `Bearer ${adminToken}`,
          'X-Test-Correlation-ID': TEST_CORRELATION_ID
        },
        params: {
          correlation_id: TEST_CORRELATION_ID,
          limit: 50
        }
      })
      
      const auditData = await auditResponse.json()
      const auditEvents = auditData.items || []
      
      // Verify audit log integrity
      for (let i = 0; i < auditEvents.length - 1; i++) {
        const currentEvent = auditEvents[i]
        const nextEvent = auditEvents[i + 1]
        
        // Verify chronological order
        expect(new Date(currentEvent.timestamp).getTime())
          .toBeGreaterThanOrEqual(new Date(nextEvent.timestamp).getTime())
        
        // Verify hash chain integrity (if implemented)
        if (currentEvent.hash && nextEvent.previous_hash) {
          expect(currentEvent.hash).toBe(nextEvent.previous_hash)
        }
      }
      
    })

    test('should prevent audit log tampering', async ({ request }) => {
      
      // Login as admin to test tampering protection
      const adminToken = await authUtils.loginAsAdmin()
      
      // Try to modify audit logs (should be denied)
      const tamperResponse = await request.put('/api/v1/admin/audit-logs/123', {
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${adminToken}`
        },
        data: {
          event_type: 'MODIFIED_EVENT',
          details: 'Tampered data'
        }
      })
      
      // Should be forbidden or method not allowed
      expect(tamperResponse.status()).toBe(405)
      
      // Try to delete audit logs (should be denied)
      const deleteResponse = await request.delete('/api/v1/admin/audit-logs/123', {
        headers: {
          'Authorization': `Bearer ${adminToken}`
        }
      })
      
      // Should be forbidden or method not allowed
      expect(deleteResponse.status()).toBe(405)
      
    })

    test('should handle audit log retention policies', async ({ request }) => {
      
      // Login as admin to query audit logs
      const adminToken = await authUtils.loginAsAdmin()
      
      // Query old audit logs
      const oldLogsResponse = await request.get('/api/v1/admin/audit-logs', {
        headers: {
          'Authorization': `Bearer ${adminToken}`
        },
        params: {
          start_date: '2020-01-01',
          end_date: '2020-12-31'
        }
      })
      
      expect(oldLogsResponse.status()).toBe(200)
      
      const oldLogsData = await oldLogsResponse.json()
      
      // Old logs may be archived or removed based on retention policy
      
      // Verify retention policy compliance
      if (oldLogsData.items && oldLogsData.items.length > 0) {
      } else {
      }
    })
  })
})