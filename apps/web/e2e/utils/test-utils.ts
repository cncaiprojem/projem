/**
 * Ultra-Enterprise Test Utilities for Task 3.15
 * 
 * Banking-grade test utilities for E2E and security testing
 * Provides comprehensive authentication testing, security validation,
 * and Turkish KVKV compliance verification utilities.
 */

import { Page, expect, APIRequestContext } from '@playwright/test'
import { randomBytes, createHash } from 'crypto'

// Test correlation ID for audit logging
export const TEST_CORRELATION_ID = `test-${Date.now()}-${randomBytes(8).toString('hex')}`

/**
 * Banking-grade authentication test utilities
 */
export class AuthTestUtils {
  constructor(
    private page: Page,
    private apiContext: APIRequestContext
  ) {}

  /**
   * Generate secure test credentials
   */
  static generateTestCredentials() {
    const timestamp = Date.now()
    const random = randomBytes(4).toString('hex')
    
    return {
      email: `test.user.${timestamp}.${random}@freecad-test.local`,
      password: `Test123!${random}`,
      firstName: 'Test',
      lastName: 'User',
      phone: '+90555123456' + random.slice(-1)
    }
  }

  /**
   * Register a new user with banking-grade validation
   */
  async registerUser(credentials: {
    email: string
    password: string
    firstName: string
    lastName: string
    phone?: string
  }) {
    await this.page.goto('/auth/register')
    
    // Fill registration form
    await this.page.fill('input[name="email"]', credentials.email)
    await this.page.fill('input[name="password"]', credentials.password)
    await this.page.fill('input[name="firstName"]', credentials.firstName)
    await this.page.fill('input[name="lastName"]', credentials.lastName)
    
    if (credentials.phone) {
      await this.page.fill('input[name="phone"]', credentials.phone)
    }

    // Accept KVKV compliance (required for Turkish users)
    await this.page.check('input[name="acceptTerms"]')
    await this.page.check('input[name="acceptKvkv"]')

    // Submit registration
    await this.page.click('button[type="submit"]')
    
    // Wait for success response
    await expect(this.page.locator('[data-testid="registration-success"]')).toBeVisible()
    
    return credentials
  }

  /**
   * Login with password-based authentication
   */
  async loginWithPassword(email: string, password: string) {
    await this.page.goto('/auth/login')
    
    await this.page.fill('input[name="email"]', email)
    await this.page.fill('input[name="password"]', password)
    
    // Add correlation ID for audit logging verification
    await this.page.addInitScript(() => {
      window.localStorage.setItem('test-correlation-id', TEST_CORRELATION_ID)
    })
    
    await this.page.click('button[type="submit"]')
    
    // Wait for successful login (could redirect to MFA)
    await this.page.waitForLoadState('networkidle')
    
    return this.page.url()
  }

  /**
   * Handle MFA challenge flow
   */
  async completeMfaChallenge(totpCode: string) {
    // Should be on MFA challenge page
    await expect(this.page).toHaveURL(/.*\/auth\/mfa\/challenge/)
    
    await this.page.fill('input[name="totpCode"]', totpCode)
    await this.page.click('button[type="submit"]')
    
    // Wait for MFA completion
    await this.page.waitForLoadState('networkidle')
    
    return this.page.url()
  }

  /**
   * Request magic link authentication
   */
  async requestMagicLink(email: string) {
    await this.page.goto('/auth/magic-link')
    
    await this.page.fill('input[name="email"]', email)
    await this.page.click('button[type="submit"]')
    
    // Should always return 202 for security (email enumeration protection)
    await expect(this.page.locator('[data-testid="magic-link-sent"]')).toBeVisible()
  }

  /**
   * Consume magic link (simulate email click)
   */
  async consumeMagicLink(token: string) {
    await this.page.goto(`/auth/magic-link/consume?token=${token}`)
    
    // Wait for authentication completion
    await this.page.waitForLoadState('networkidle')
    
    return this.page.url()
  }

  /**
   * Initiate OIDC flow with Google (mocked)
   */
  async initiateOidcFlow() {
    await this.page.goto('/auth/oidc/google')
    
    // Click Google login button
    await this.page.click('[data-testid="google-login-button"]')
    
    // Should redirect to mock OIDC provider or real Google
    await this.page.waitForLoadState('networkidle')
    
    return this.page.url()
  }

  /**
   * Complete OIDC callback flow
   */
  async completeOidcCallback(code: string, state: string) {
    await this.page.goto(`/auth/oidc/callback?code=${code}&state=${state}`)
    
    // Wait for authentication completion
    await this.page.waitForLoadState('networkidle')
    
    return this.page.url()
  }

  /**
   * Logout and validate session cleanup
   */
  async logout() {
    await this.page.click('[data-testid="user-menu"]')
    await this.page.click('[data-testid="logout-button"]')
    
    // Wait for logout completion
    await this.page.waitForLoadState('networkidle')
    
    // Validate redirected to login
    await expect(this.page).toHaveURL(/.*\/auth\/login/)
    
    // Validate session cleanup
    const cookies = await this.page.context().cookies()
    const authCookies = cookies.filter(c => 
      c.name.includes('access_token') || 
      c.name.includes('refresh_token') ||
      c.name.includes('rt')
    )
    
    expect(authCookies).toHaveLength(0)
  }

  /**
   * Validate user is authenticated
   */
  async validateAuthenticated() {
    // Check for auth indicators
    await expect(this.page.locator('[data-testid="user-menu"]')).toBeVisible()
    
    // Validate access to protected route
    await this.page.goto('/dashboard')
    await expect(this.page).toHaveURL(/.*\/dashboard/)
  }

  /**
   * Validate user is not authenticated
   */
  async validateNotAuthenticated() {
    // Try to access protected route
    await this.page.goto('/dashboard')
    
    // Should redirect to login
    await expect(this.page).toHaveURL(/.*\/auth\/login/)
  }

  /**
   * Login as admin user for testing protected admin endpoints
   */
  async loginAsAdmin(): Promise<string> {
    // Use pre-created admin user from global setup
    const adminCredentials = {
      email: 'admin.tester@freecad-test.local',
      password: 'AdminTest123!'
    }
    
    const response = await this.apiContext.post('/api/v1/auth/login', {
      headers: {
        'Content-Type': 'application/json',
        'X-Test-Correlation-ID': TEST_CORRELATION_ID
      },
      data: {
        email: adminCredentials.email,
        password: adminCredentials.password
      }
    })
    
    if (!response.ok()) {
      throw new Error(`Admin login failed: ${response.status()}`)
    }
    
    const loginData = await response.json()
    return loginData.access_token
  }
}

/**
 * Security testing utilities
 */
export class SecurityTestUtils {
  constructor(
    private page: Page,
    private apiContext: APIRequestContext
  ) {}

  /**
   * Validate CSRF protection
   */
  async validateCsrfProtection() {
    // Get CSRF token from page
    const csrfToken = await this.page.evaluate(() => {
      return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
    })
    
    expect(csrfToken).toBeTruthy()
    
    // Attempt request without CSRF token (should fail)
    const response = await this.apiContext.post('/api/v1/auth/login', {
      headers: {
        'Content-Type': 'application/json',
      },
      data: {
        email: 'test@example.com',
        password: 'password'
      }
    })
    
    expect(response.status()).toBe(403) // Should be forbidden without CSRF token
    
    const errorData = await response.json()
    expect(errorData.error_code).toBe('ERR_CSRF_INVALID')
  }

  /**
   * Test XSS protection
   */
  async validateXssProtection() {
    const xssPayload = '<script>alert("xss")</script>'
    
    // Try to inject XSS in various inputs
    await this.page.goto('/auth/login')
    
    await this.page.fill('input[name="email"]', xssPayload)
    await this.page.fill('input[name="password"]', 'password')
    
    await this.page.click('button[type="submit"]')
    
    // Wait for form submission to complete
    await this.page.waitForLoadState('networkidle')
    
    // Validate XSS was not executed
    const alertDialogs = this.page.locator('role=dialog')
    await expect(alertDialogs).toHaveCount(0)
    
    // Validate input sanitization
    const emailValue = await this.page.inputValue('input[name="email"]')
    expect(emailValue).not.toContain('<script>')
  }

  /**
   * Validate rate limiting
   */
  async validateRateLimit(endpoint: string, limit: number) {
    const requests = []
    
    // Make requests up to the limit
    for (let i = 0; i < limit + 1; i++) {
      requests.push(
        this.apiContext.post(endpoint, {
          headers: {
            'Content-Type': 'application/json',
            'X-Test-Correlation-ID': TEST_CORRELATION_ID
          },
          data: {
            email: 'test@example.com',
            password: 'password'
          }
        })
      )
    }
    
    const responses = await Promise.all(requests)
    
    // Last request should be rate limited
    const lastResponse = responses[responses.length - 1]
    expect(lastResponse.status()).toBe(429)
    
    const errorData = await lastResponse.json()
    expect(errorData.error_code).toBe('ERR_RATE_LIMIT_EXCEEDED')
    
    // Should have Retry-After header
    const retryAfter = lastResponse.headers()['retry-after']
    expect(retryAfter).toBeTruthy()
    expect(parseInt(retryAfter)).toBeGreaterThan(0)
  }

  /**
   * Validate security headers
   */
  async validateSecurityHeaders() {
    const response = await this.apiContext.get('/')
    
    const headers = response.headers()
    
    // Validate essential security headers
    expect(headers['x-frame-options']).toBe('DENY')
    expect(headers['x-content-type-options']).toBe('nosniff')
    expect(headers['x-xss-protection']).toBe('1; mode=block')
    expect(headers['strict-transport-security']).toContain('max-age=')
    expect(headers['content-security-policy']).toBeTruthy()
    expect(headers['referrer-policy']).toBe('strict-origin-when-cross-origin')
    expect(headers['permissions-policy']).toBeTruthy()
  }

  /**
   * Validate cookie security attributes
   */
  async validateCookieSecurity() {
    // Login to get cookies
    await this.page.goto('/auth/login')
    
    const cookies = await this.page.context().cookies()
    
    // Validate auth cookies have security attributes
    const authCookies = cookies.filter(c => 
      c.name.includes('rt') || 
      c.name.includes('csrf') ||
      c.name.includes('session')
    )
    
    for (const cookie of authCookies) {
      expect(cookie.httpOnly).toBe(true)
      expect(cookie.secure).toBe(true) // Should be true in production
      expect(cookie.sameSite).toBe('Strict')
    }
  }
}

/**
 * API testing utilities
 */
export class ApiTestUtils {
  constructor(private apiContext: APIRequestContext) {}

  /**
   * Test all authentication endpoints comprehensively
   */
  async testAuthEndpoints() {
    const testCredentials = AuthTestUtils.generateTestCredentials()
    
    // Test registration endpoint
    const registerResponse = await this.apiContext.post('/api/v1/auth/register', {
      headers: {
        'Content-Type': 'application/json',
        'X-Test-Correlation-ID': TEST_CORRELATION_ID
      },
      data: testCredentials
    })
    
    expect(registerResponse.status()).toBe(201)
    
    // Test login endpoint
    const loginResponse = await this.apiContext.post('/api/v1/auth/login', {
      headers: {
        'Content-Type': 'application/json',
        'X-Test-Correlation-ID': TEST_CORRELATION_ID
      },
      data: {
        email: testCredentials.email,
        password: testCredentials.password
      }
    })
    
    expect(loginResponse.status()).toBe(200)
    
    const loginData = await loginResponse.json()
    expect(loginData.access_token).toBeTruthy()
    expect(loginData.refresh_token).toBeTruthy()
    
    return { testCredentials, tokens: loginData }
  }

  /**
   * Test protected endpoints with authentication
   */
  async testProtectedEndpoints(accessToken: string) {
    const response = await this.apiContext.get('/api/v1/me', {
      headers: {
        'Authorization': `Bearer ${accessToken}`,
        'X-Test-Correlation-ID': TEST_CORRELATION_ID
      }
    })
    
    expect(response.status()).toBe(200)
    
    const userData = await response.json()
    expect(userData.id).toBeTruthy()
    expect(userData.email).toBeTruthy()
  }

  /**
   * Test token refresh flow
   */
  async testTokenRefresh(refreshToken: string) {
    const response = await this.apiContext.post('/api/v1/auth/refresh', {
      headers: {
        'Content-Type': 'application/json',
        'X-Test-Correlation-ID': TEST_CORRELATION_ID
      },
      data: {
        refresh_token: refreshToken
      }
    })
    
    expect(response.status()).toBe(200)
    
    const refreshData = await response.json()
    expect(refreshData.access_token).toBeTruthy()
    expect(refreshData.refresh_token).toBeTruthy()
    
    return refreshData
  }
}

/**
 * Performance and monitoring utilities
 */
export class PerformanceTestUtils {
  constructor(private page: Page) {}

  /**
   * Measure page load performance
   */
  async measurePageLoad(url: string) {
    const startTime = Date.now()
    
    await this.page.goto(url, { waitUntil: 'networkidle' })
    
    const endTime = Date.now()
    const loadTime = endTime - startTime
    
    // Banking-grade performance requirements
    expect(loadTime).toBeLessThan(3000) // 3 seconds max
    
    // Measure Core Web Vitals
    const metrics = await this.page.evaluate(() => {
      return {
        // @ts-ignore
        fcp: performance.getEntriesByName('first-contentful-paint')[0]?.startTime,
        // @ts-ignore
        lcp: performance.getEntriesByType('largest-contentful-paint')[0]?.startTime,
      }
    })
    
    return { loadTime, ...metrics }
  }

  /**
   * Monitor network performance
   */
  async monitorNetworkPerformance() {
    const responses: any[] = []
    
    this.page.on('response', response => {
      responses.push({
        url: response.url(),
        status: response.status(),
        timing: response.timing()
      })
    })
    
    return responses
  }
}

/**
 * Audit logging verification utilities
 */
export class AuditTestUtils {
  constructor(private apiContext: APIRequestContext) {}

  /**
   * Verify audit events were created
   */
  async verifyAuditEvents(correlationId: string, expectedEvents: string[], adminToken?: string) {
    // Give time for audit events to be processed
    await new Promise(resolve => setTimeout(resolve, 1000))
    
    // Get admin token if not provided
    if (!adminToken) {
      const authUtils = new AuthTestUtils(undefined as any, this.apiContext)
      adminToken = await authUtils.loginAsAdmin()
    }
    
    const response = await this.apiContext.get(`/api/v1/admin/audit-logs`, {
      headers: {
        'Authorization': `Bearer ${adminToken}`,
        'X-Test-Correlation-ID': correlationId
      },
      params: {
        correlation_id: correlationId,
        limit: 50
      }
    })
    
    expect(response.status()).toBe(200)
    
    const auditData = await response.json()
    const events = auditData.items || []
    
    // Verify all expected events were logged
    for (const expectedEvent of expectedEvents) {
      const eventFound = events.some((event: any) => 
        event.event_type === expectedEvent &&
        event.correlation_id === correlationId
      )
      
      expect(eventFound).toBe(true)
    }
  }

  /**
   * Verify KVKV compliance in audit logs
   */
  async verifyKvkvCompliance(correlationId: string, adminToken?: string) {
    // Get admin token if not provided
    if (!adminToken) {
      const authUtils = new AuthTestUtils(undefined as any, this.apiContext)
      adminToken = await authUtils.loginAsAdmin()
    }
    
    const response = await this.apiContext.get(`/api/v1/admin/audit-logs`, {
      headers: {
        'Authorization': `Bearer ${adminToken}`,
        'X-Test-Correlation-ID': correlationId
      },
      params: {
        correlation_id: correlationId
      }
    })
    
    const auditData = await response.json()
    const events = auditData.items || []
    
    // Verify no PII is exposed in audit logs
    for (const event of events) {
      expect(event.details).not.toMatch(/\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b/) // No email addresses
      expect(event.details).not.toMatch(/\b\d{11}\b/) // No Turkish ID numbers
      expect(event.details).not.toMatch(/\+90\d{10}\b/) // No phone numbers
    }
  }
}

// Export test utilities
export {
  TEST_CORRELATION_ID,
  AuthTestUtils,
  SecurityTestUtils,
  ApiTestUtils,
  PerformanceTestUtils,
  AuditTestUtils
}