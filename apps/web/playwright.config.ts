import { defineConfig, devices } from '@playwright/test'

/**
 * Ultra-Enterprise Security Testing Configuration for Task 3.15
 * 
 * Banking-grade E2E and security testing with Turkish KVKV compliance
 * Supports comprehensive authentication flow testing and security validation
 */
export default defineConfig({
  // Test directory structure
  testDir: './e2e',
  
  // Global test configuration
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  
  // Reporter configuration for CI/CD integration
  reporter: [
    ['html', { outputFolder: 'playwright-report' }],
    ['junit', { outputFile: 'test-results/junit.xml' }],
    ['json', { outputFile: 'test-results/results.json' }]
  ],
  
  // Global test timeout and timeouts
  timeout: 30 * 1000, // 30 seconds for banking-grade reliability
  expect: {
    timeout: 10 * 1000, // 10 seconds for assertions
  },
  
  use: {
    // Base configuration
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:3000',
    
    // Browser context options for security testing
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    
    // Security headers validation
    extraHTTPHeaders: {
      'Accept-Language': 'tr-TR,tr;q=0.9,en;q=0.8', // Turkish localization
    },
    
    // Mobile viewport for responsive testing
    viewport: { width: 1280, height: 720 },
    
    // User agent for consistent testing
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 - FreeCadE2ETest',
    
    // Geolocation for Turkish locale testing
    locale: 'tr-TR',
    timezoneId: 'Europe/Istanbul',
    
    // Security testing context
    ignoreHTTPSErrors: false, // Enforce HTTPS in production tests
    bypassCSP: false, // Never bypass CSP for security testing
  },

  projects: [
    // Desktop browsers for comprehensive testing
    {
      name: 'chromium-security',
      use: { 
        ...devices['Desktop Chrome'],
        // Additional security context
        channel: 'chrome',
        launchOptions: {
          args: [
            '--disable-web-security=false', // Enforce web security
            '--disable-features=VizDisplayCompositor',
          ]
        }
      },
      testMatch: /.*security.*\.spec\.ts/,
    },
    
    {
      name: 'firefox-auth',
      use: { 
        ...devices['Desktop Firefox'],
      },
      testMatch: /.*auth.*\.spec\.ts/,
    },
    
    {
      name: 'webkit-cross-browser',
      use: { 
        ...devices['Desktop Safari'],
      },
      testMatch: /.*cross-browser.*\.spec\.ts/,
    },
    
    // Mobile testing for responsive auth flows
    {
      name: 'mobile-chrome',
      use: { 
        ...devices['Pixel 5'],
      },
      testMatch: /.*mobile.*\.spec\.ts/,
    },
    
    // API testing project
    {
      name: 'api-security',
      testMatch: /.*api.*\.spec\.ts/,
      use: {
        baseURL: process.env.PLAYWRIGHT_API_BASE_URL || 'http://localhost:8000',
      },
    },
  ],

  // Global setup and teardown
  globalSetup: './e2e/setup/global-setup.ts',
  globalTeardown: './e2e/setup/global-setup.ts',

  // Web server configuration for testing
  webServer: [
    {
      command: 'cd ../api && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload',
      url: 'http://localhost:8000/healthz',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000, // 2 minutes startup time
      env: {
        NODE_ENV: 'test',
        DATABASE_URL: 'postgresql+psycopg2://freecad:password@localhost:5432/freecad_test',
        REDIS_URL: 'redis://localhost:6379/1',
        DEV_AUTH_BYPASS: 'false', // Never bypass auth in tests
      },
    },
    {
      command: 'pnpm dev',
      url: 'http://localhost:3000',
      reuseExistingServer: !process.env.CI,
      timeout: 120 * 1000,
      env: {
        NODE_ENV: 'test',
        NEXT_PUBLIC_API_BASE_URL: 'http://localhost:8000',
      },
    },
  ],
})


