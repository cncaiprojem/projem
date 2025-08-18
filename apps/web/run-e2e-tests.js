/**
 * Ultra-Enterprise E2E Test Runner - Task 3.15
 * 
 * Comprehensive test execution script for banking-grade security testing
 * with Turkish KVKV compliance and complete audit trail generation.
 */

const { spawn } = require('child_process')
const fs = require('fs')
const path = require('path')

// Test configuration
const TEST_CONFIG = {
  suites: {
    auth: {
      name: 'Authentication Flows',
      pattern: '**/auth/*.spec.ts',
      critical: true,
      timeout: 300000 // 5 minutes
    },
    security: {
      name: 'Security Vulnerabilities',
      pattern: '**/security/*.spec.ts',
      critical: true,
      timeout: 600000 // 10 minutes
    },
    api: {
      name: 'API Endpoints',
      pattern: '**/api/*.spec.ts',
      critical: true,
      timeout: 300000 // 5 minutes
    },
    audit: {
      name: 'Audit Logging',
      pattern: '**/audit/*.spec.ts',
      critical: true,
      timeout: 300000 // 5 minutes
    },
    ci: {
      name: 'CI/CD Integration',
      pattern: '**/ci/*.spec.ts',
      critical: false,
      timeout: 600000 // 10 minutes
    }
  },
  reporting: {
    html: true,
    junit: true,
    json: true,
    coverage: true
  },
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : 2,
  headless: process.env.CI ? true : false
}

// Colors for console output
const colors = {
  reset: '\x1b[0m',
  bright: '\x1b[1m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m'
}

function log(message, color = 'reset') {
  console.log(`${colors[color]}${message}${colors.reset}`)
}

function logSection(title) {
  log('\n' + '='.repeat(60), 'cyan')
  log(`  ${title}`, 'bright')
  log('='.repeat(60), 'cyan')
}

function logStep(step, status = 'info') {
  const icon = status === 'success' ? '✅' : status === 'error' ? '❌' : status === 'warning' ? '⚠️' : 'ℹ️'
  const color = status === 'success' ? 'green' : status === 'error' ? 'red' : status === 'warning' ? 'yellow' : 'blue'
  log(`${icon} ${step}`, color)
}

async function runCommand(command, args = [], options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: 'inherit',
      shell: true,
      ...options
    })

    child.on('close', (code) => {
      if (code === 0) {
        resolve(code)
      } else {
        reject(new Error(`Command failed with exit code ${code}`))
      }
    })

    child.on('error', (error) => {
      reject(error)
    })
  })
}

async function setupTestEnvironment() {
  logStep('Setting up test environment...')
  
  try {
    // Ensure test results directory exists
    const resultsDir = path.join(__dirname, 'test-results')
    if (!fs.existsSync(resultsDir)) {
      fs.mkdirSync(resultsDir, { recursive: true })
    }
    
    // Ensure security reports directory exists
    const securityDir = path.join(resultsDir, 'security-reports')
    if (!fs.existsSync(securityDir)) {
      fs.mkdirSync(securityDir, { recursive: true })
    }
    
    logStep('Test environment setup completed', 'success')
  } catch (error) {
    logStep(`Test environment setup failed: ${error.message}`, 'error')
    throw error
  }
}

async function runTestSuite(suiteName, config) {
  logStep(`Running ${config.name} tests...`)
  
  const args = [
    'test',
    '--grep', config.pattern,
    '--timeout', config.timeout.toString(),
    '--retries', TEST_CONFIG.retries.toString(),
    '--workers', TEST_CONFIG.workers.toString()
  ]
  
  if (TEST_CONFIG.headless) {
    args.push('--headed=false')
  }
  
  // Add reporters
  if (TEST_CONFIG.reporting.html) {
    args.push('--reporter=html')
  }
  
  if (TEST_CONFIG.reporting.junit) {
    args.push('--reporter=junit')
  }
  
  try {
    await runCommand('npx', ['playwright', ...args])
    logStep(`${config.name} tests completed successfully`, 'success')
    return { suite: suiteName, status: 'PASS', critical: config.critical }
  } catch (error) {
    logStep(`${config.name} tests failed: ${error.message}`, 'error')
    return { suite: suiteName, status: 'FAIL', critical: config.critical, error: error.message }
  }
}

async function generateComprehensiveReport(results) {
  logStep('Generating comprehensive test report...')
  
  const report = {
    timestamp: new Date().toISOString(),
    environment: process.env.NODE_ENV || 'test',
    branch: process.env.GITHUB_REF_NAME || 'unknown',
    commit: process.env.GITHUB_SHA || 'unknown',
    results: results,
    summary: {
      total: results.length,
      passed: results.filter(r => r.status === 'PASS').length,
      failed: results.filter(r => r.status === 'FAIL').length,
      critical_failed: results.filter(r => r.status === 'FAIL' && r.critical).length
    }
  }
  
  // Determine overall status
  report.summary.overall_status = report.summary.critical_failed === 0 ? 'PASS' : 'FAIL'
  
  // Write report to file
  const reportPath = path.join(__dirname, 'test-results', 'comprehensive-report.json')
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2))
  
  // Generate markdown report
  const markdownReport = generateMarkdownReport(report)
  const markdownPath = path.join(__dirname, 'test-results', 'test-report.md')
  fs.writeFileSync(markdownPath, markdownReport)
  
  logStep('Comprehensive test report generated', 'success')
  
  return report
}

function generateMarkdownReport(report) {
  const status = report.summary.overall_status === 'PASS' ? '✅ PASSED' : '❌ FAILED'
  
  return `
# Ultra-Enterprise E2E Test Report - Task 3.15

**Overall Status:** ${status}  
**Timestamp:** ${report.timestamp}  
**Environment:** ${report.environment}  
**Branch:** ${report.branch}  
**Commit:** ${report.commit}

## Summary

- **Total Test Suites:** ${report.summary.total}
- **Passed:** ${report.summary.passed}
- **Failed:** ${report.summary.failed}
- **Critical Failures:** ${report.summary.critical_failed}

## Test Suite Results

${report.results.map(result => {
  const statusIcon = result.status === 'PASS' ? '✅' : '❌'
  const criticalBadge = result.critical ? '🔴 CRITICAL' : '🔵 OPTIONAL'
  
  return `### ${statusIcon} ${result.suite} ${criticalBadge}
  
**Status:** ${result.status}
${result.error ? `**Error:** ${result.error}` : ''}
`
}).join('\n')}

## Banking-Grade Security Compliance

${report.summary.critical_failed === 0 ? 
  '✅ All critical security tests passed. Application meets banking-grade security standards.' : 
  '❌ Critical security tests failed. Application does not meet banking-grade security standards.'}

## Turkish KVKV Compliance

${report.results.find(r => r.suite === 'audit' && r.status === 'PASS') ? 
  '✅ Turkish KVKV compliance tests passed. Data protection requirements met.' : 
  '❌ Turkish KVKV compliance tests failed. Review data protection implementation.'}

## Recommendations

${report.summary.overall_status === 'PASS' ? 
  '- All tests passed. Application is ready for production deployment.\n- Continue monitoring and regular security testing.' : 
  '- Address critical test failures before deployment.\n- Review security implementation and audit logging.\n- Ensure Turkish localization is complete.'}

---
*Generated by Ultra-Enterprise E2E Test Suite - Task 3.15*
`
}

async function main() {
  logSection('Ultra-Enterprise E2E Test Execution - Task 3.15')
  
  log('🔒 Banking-grade security testing with Turkish KVKV compliance', 'bright')
  log('🇹🇷 Comprehensive authentication and audit validation', 'bright')
  
  try {
    // Setup
    await setupTestEnvironment()
    
    // Run test suites
    const results = []
    
    for (const [suiteName, config] of Object.entries(TEST_CONFIG.suites)) {
      logSection(`Test Suite: ${config.name}`)
      
      const result = await runTestSuite(suiteName, config)
      results.push(result)
      
      // Stop on critical failures if in CI
      if (result.status === 'FAIL' && result.critical && process.env.CI) {
        logStep('Critical test failure detected in CI - stopping execution', 'error')
        break
      }
    }
    
    // Generate comprehensive report
    logSection('Test Results Summary')
    
    const report = await generateComprehensiveReport(results)
    
    // Display summary
    logStep(`Total Suites: ${report.summary.total}`)
    logStep(`Passed: ${report.summary.passed}`, 'success')
    logStep(`Failed: ${report.summary.failed}`, report.summary.failed > 0 ? 'error' : 'success')
    logStep(`Critical Failures: ${report.summary.critical_failed}`, report.summary.critical_failed > 0 ? 'error' : 'success')
    
    logStep(`Overall Status: ${report.summary.overall_status}`, 
      report.summary.overall_status === 'PASS' ? 'success' : 'error')
    
    // Banking-grade validation
    if (report.summary.critical_failed === 0) {
      logStep('Banking-grade security standards met', 'success')
    } else {
      logStep('Banking-grade security standards NOT met', 'error')
    }
    
    // KVKV compliance validation
    const auditResult = results.find(r => r.suite === 'audit')
    if (auditResult && auditResult.status === 'PASS') {
      logStep('Turkish KVKV compliance validated', 'success')
    } else {
      logStep('Turkish KVKV compliance validation failed', 'error')
    }
    
    logSection('Test Execution Completed')
    
    // Exit with appropriate code
    process.exit(report.summary.overall_status === 'PASS' ? 0 : 1)
    
  } catch (error) {
    logStep(`Test execution failed: ${error.message}`, 'error')
    process.exit(1)
  }
}

// Handle uncaught exceptions
process.on('uncaughtException', (error) => {
  logStep(`Uncaught exception: ${error.message}`, 'error')
  process.exit(1)
})

process.on('unhandledRejection', (error) => {
  logStep(`Unhandled rejection: ${error.message}`, 'error')
  process.exit(1)
})

// Run main function
if (require.main === module) {
  main()
}

module.exports = { main, TEST_CONFIG }