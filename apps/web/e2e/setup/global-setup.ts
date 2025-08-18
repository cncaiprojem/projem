/**
 * Global Test Setup for Ultra-Enterprise Security Testing - Task 3.15
 * 
 * Sets up comprehensive test infrastructure including:
 * - Mock OIDC server for authentication testing
 * - Security scanning tools
 * - Test database preparation
 * - Turkish localization setup
 */

import { chromium, FullConfig } from '@playwright/test'
import { MockOidcServer, MockEmailService, MockSmsService } from '../utils/mock-server'
import { exec } from 'child_process'
import { promisify } from 'util'
import path from 'path'

const execAsync = promisify(exec)

// Global test state
export const globalTestState = {
  mockOidcServer: new MockOidcServer(9999),
  mockEmailService: new MockEmailService(),
  mockSmsService: new MockSmsService(),
  zapProxyStarted: false,
  testDbReady: false
}

async function globalSetup(config: FullConfig) {
  console.log('🚀 Starting Ultra-Enterprise Security Test Infrastructure...')
  
  try {
    // Start mock services
    await setupMockServices()
    
    // Setup test database
    await setupTestDatabase()
    
    // Start ZAP proxy if needed
    await setupZapProxy()
    
    // Verify API and web servers are ready
    await verifyTestEnvironment()
    
    // Setup test user accounts
    await setupTestUsers()
    
    console.log('✅ Test infrastructure ready for banking-grade security testing')
    
  } catch (error) {
    console.error('❌ Failed to setup test infrastructure:', error)
    process.exit(1)
  }
}

/**
 * Setup mock services for isolated testing
 */
async function setupMockServices() {
  console.log('📡 Starting mock services...')
  
  try {
    // Start mock OIDC server
    await globalTestState.mockOidcServer.start()
    console.log('✅ Mock OIDC server started on port 9999')
    
    // Clear mock services
    globalTestState.mockEmailService.clear()
    globalTestState.mockSmsService.clear()
    
    console.log('✅ Mock email and SMS services initialized')
  } catch (error) {
    throw new Error(`Failed to setup mock services: ${error}`)
  }
}

/**
 * Setup test database with clean state
 */
async function setupTestDatabase() {
  console.log('🗄️ Setting up test database...')
  
  try {
    // Run database migrations for test environment
    const apiPath = path.resolve(__dirname, '../../../../api')
    const { stdout: migrateOutput } = await execAsync(
      'python -m alembic upgrade head',
      { 
        cwd: apiPath,
        env: { 
          ...process.env, 
          DATABASE_URL: process.env.TEST_DATABASE_URL || 'postgresql+psycopg2://freecad:password@localhost:5432/freecad_test',
          NODE_ENV: 'test'
        }
      }
    )
    console.log('✅ Database migrations applied')
    
    // Clear test data and seed basic data
    await execAsync(
      'python -m app.scripts.seed_test_data',
      { 
        cwd: apiPath,
        env: { 
          ...process.env, 
          DATABASE_URL: process.env.TEST_DATABASE_URL || 'postgresql+psycopg2://freecad:password@localhost:5432/freecad_test'
        }
      }
    )
    console.log('✅ Test data seeded')
    
    globalTestState.testDbReady = true
  } catch (error) {
    throw new Error(`Failed to setup test database: ${error}`)
  }
}

/**
 * Setup ZAP proxy for security testing
 */
async function setupZapProxy() {
  console.log('🔒 Setting up ZAP security proxy...')
  
  try {
    // Check if ZAP is available
    await execAsync('zap.sh -version', { timeout: 5000 })
    
    // ZAP will be started on-demand by individual tests
    console.log('✅ ZAP security scanner available')
    
  } catch (error) {
    console.warn('⚠️  ZAP not available - security scans will be skipped')
    console.warn('Install OWASP ZAP for complete security testing')
  }
}

/**
 * Verify test environment is ready
 */
async function verifyTestEnvironment() {
  console.log('🔍 Verifying test environment...')
  
  // Create browser instance for environment verification
  const browser = await chromium.launch()
  const page = await browser.newPage()
  
  try {
    // Check API health endpoint
    const apiResponse = await page.goto('http://localhost:8000/healthz')
    if (!apiResponse?.ok()) {
      throw new Error('API server not responding')
    }
    console.log('✅ API server ready')
    
    // Check web application
    const webResponse = await page.goto('http://localhost:3000')
    if (!webResponse?.ok()) {
      throw new Error('Web server not responding')
    }
    console.log('✅ Web server ready')
    
    // Verify Turkish localization is working
    await page.goto('http://localhost:3000/auth/login')
    const turkishContent = await page.locator('text=Giriş').first()
    if (!(await turkishContent.isVisible())) {
      console.warn('⚠️  Turkish localization may not be working correctly')
    } else {
      console.log('✅ Turkish localization verified')
    }
    
  } catch (error) {
    throw new Error(`Environment verification failed: ${error}`)
  } finally {
    await browser.close()
  }
}

/**
 * Setup test user accounts for various testing scenarios
 */
async function setupTestUsers() {
  console.log('👥 Setting up test user accounts...')
  
  const browser = await chromium.launch()
  const page = await browser.newPage()
  
  try {
    const testUsers = [
      {
        email: 'security.tester@freecad-test.local',
        password: 'SecureTest123!',
        firstName: 'Security',
        lastName: 'Tester',
        role: 'user'
      },
      {
        email: 'admin.tester@freecad-test.local', 
        password: 'AdminTest123!',
        firstName: 'Admin',
        lastName: 'Tester',
        role: 'admin'
      },
      {
        email: 'mfa.tester@freecad-test.local',
        password: 'MfaTest123!',
        firstName: 'MFA',
        lastName: 'Tester',
        role: 'user'
      }
    ]
    
    for (const user of testUsers) {
      try {
        // Register test user via API
        const response = await page.request.post('http://localhost:8000/api/v1/auth/register', {
          headers: { 'Content-Type': 'application/json' },
          data: {
            email: user.email,
            password: user.password,
            firstName: user.firstName,
            lastName: user.lastName,
            acceptTerms: true,
            acceptKvkv: true
          }
        })
        
        if (response.ok()) {
          console.log(`✅ Test user created: ${user.email}`)
        } else {
          console.log(`ℹ️  User may already exist: ${user.email}`)
        }
      } catch (error) {
        console.warn(`⚠️  Failed to create user ${user.email}:`, error)
      }
    }
    
  } finally {
    await browser.close()
  }
}

/**
 * Global teardown - cleanup resources
 */
export async function globalTeardown() {
  console.log('🧹 Cleaning up test infrastructure...')
  
  try {
    // Stop mock services
    await globalTestState.mockOidcServer.stop()
    console.log('✅ Mock OIDC server stopped')
    
    // Clear test data if needed
    globalTestState.mockEmailService.clear()
    globalTestState.mockSmsService.clear()
    
    console.log('✅ Test infrastructure cleanup completed')
  } catch (error) {
    console.error('❌ Error during cleanup:', error)
  }
}

// Export for Playwright configuration
export default globalSetup