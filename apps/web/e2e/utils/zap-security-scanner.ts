/**
 * OWASP ZAP Security Scanner Integration for Task 3.15
 * 
 * Ultra-enterprise security scanning with OWASP ZAP for banking-grade
 * vulnerability assessment and compliance verification.
 */

import { Page } from '@playwright/test'
import { exec } from 'child_process'
import { promisify } from 'util'
import fs from 'fs/promises'
import path from 'path'

const execAsync = promisify(exec)

interface ZapScanConfig {
  target: string
  zapProxy: string
  zapApiKey?: string
  scanPolicies: string[]
  contextName: string
  excludeUrls?: string[]
  includeUrls?: string[]
  maxScanDuration: number
  reportFormats: string[]
}

interface ZapAlert {
  alert: string
  name: string
  riskdesc: string
  confidence: string
  riskcode: string
  desc: string
  uri: string
  param: string
  attack: string
  evidence: string
  solution: string
  reference: string
  cweid: string
  wascid: string
  sourceid: string
}

interface ZapScanResults {
  alerts: ZapAlert[]
  summary: {
    high: number
    medium: number
    low: number
    informational: number
    total: number
  }
  scanInfo: {
    startTime: string
    endTime: string
    duration: number
    target: string
    status: string
  }
  compliance: {
    kvkv: boolean
    owasp: boolean
    banking: boolean
  }
}

export class ZapSecurityScanner {
  private config: ZapScanConfig
  private zapBaseUrl: string
  private apiKey?: string

  constructor(config: Partial<ZapScanConfig> = {}) {
    this.config = {
      target: 'http://localhost:3000',
      zapProxy: 'http://localhost:8080',
      contextName: 'FreeCadE2ETest',
      scanPolicies: ['Default Policy'],
      maxScanDuration: 300000, // 5 minutes
      reportFormats: ['json', 'html', 'xml'],
      ...config
    }
    
    this.zapBaseUrl = this.config.zapProxy.replace(':8080', ':8080')
    // ZAP API key sourced from environment variable for security
    this.apiKey = this.config.zapApiKey || process.env.ZAP_API_KEY
  }

  /**
   * Start ZAP proxy if not already running
   */
  async startZapProxy(): Promise<void> {
    try {
      // Check if ZAP is already running
      await this.makeZapApiCall('core/view/version/')
      console.log('ZAP proxy is already running')
      return
    } catch (error) {
      console.log('Starting ZAP proxy...')
    }

    try {
      // Start ZAP in daemon mode
      const zapCommand = `zap.sh -daemon -host 0.0.0.0 -port 8080 -config api.addrs.addr.name=.* -config api.addrs.addr.regex=true ${this.apiKey ? `-config api.key=${this.apiKey}` : ''}`
      
      const zapProcess = exec(zapCommand, (error, stdout, stderr) => {
        if (error) {
          console.error('ZAP startup error:', error)
          return
        }
        console.log('ZAP stdout:', stdout)
        if (stderr) {
          console.error('ZAP stderr:', stderr)
        }
      })

      // Wait for ZAP to start
      await this.waitForZapStartup()
      console.log('ZAP proxy started successfully')
    } catch (error) {
      throw new Error(`Failed to start ZAP proxy: ${error}`)
    }
  }

  /**
   * Wait for ZAP to be fully started
   */
  private async waitForZapStartup(maxWaitTime = 60000): Promise<void> {
    const startTime = Date.now()
    
    while (Date.now() - startTime < maxWaitTime) {
      try {
        await this.makeZapApiCall('core/view/version/')
        return
      } catch (error) {
        await new Promise(resolve => setTimeout(resolve, 1000))
      }
    }
    
    throw new Error('ZAP failed to start within timeout period')
  }

  /**
   * Configure ZAP context for authentication testing
   */
  async configureContext(): Promise<void> {
    try {
      // Create context
      await this.makeZapApiCall('context/action/newContext/', {
        contextName: this.config.contextName
      })

      // Include URLs in context
      if (this.config.includeUrls?.length) {
        for (const url of this.config.includeUrls) {
          await this.makeZapApiCall('context/action/includeInContext/', {
            contextName: this.config.contextName,
            regex: url
          })
        }
      } else {
        await this.makeZapApiCall('context/action/includeInContext/', {
          contextName: this.config.contextName,
          regex: `${this.config.target}.*`
        })
      }

      // Exclude URLs from context
      if (this.config.excludeUrls?.length) {
        for (const url of this.config.excludeUrls) {
          await this.makeZapApiCall('context/action/excludeFromContext/', {
            contextName: this.config.contextName,
            regex: url
          })
        }
      }

      // Configure authentication for protected endpoints
      await this.configureAuthentication()

      console.log('ZAP context configured successfully')
    } catch (error) {
      throw new Error(`Failed to configure ZAP context: ${error}`)
    }
  }

  /**
   * Configure authentication for ZAP scanning
   */
  private async configureAuthentication(): Promise<void> {
    // Set up form-based authentication for login
    await this.makeZapApiCall('authentication/action/setAuthenticationMethod/', {
      contextId: '0', // Default context ID
      authMethodName: 'formBasedAuthentication',
      authMethodConfigParams: 'loginUrl=' + encodeURIComponent(`${this.config.target}/auth/login`) +
        '&loginRequestData=' + encodeURIComponent('email={%username%}&password={%password%}')
    })

    // Set logged in indicator
    await this.makeZapApiCall('authentication/action/setLoggedInIndicator/', {
      contextId: '0',
      loggedInIndicatorRegex: '\\Qdashboard\\E'
    })

    // Set logged out indicator
    await this.makeZapApiCall('authentication/action/setLoggedOutIndicator/', {
      contextId: '0',
      loggedOutIndicatorRegex: '\\Qlogin\\E'
    })
  }

  /**
   * Perform passive scan spider
   */
  async spiderScan(): Promise<void> {
    try {
      console.log('Starting spider scan...')
      
      // Start spider
      const response = await this.makeZapApiCall('spider/action/scan/', {
        url: this.config.target,
        contextName: this.config.contextName
      })

      const scanId = response.scan

      // Monitor spider progress
      await this.monitorScanProgress('spider', scanId)
      
      console.log('Spider scan completed')
    } catch (error) {
      throw new Error(`Spider scan failed: ${error}`)
    }
  }

  /**
   * Perform active security scan
   */
  async activeScan(): Promise<void> {
    try {
      console.log('Starting active security scan...')
      
      // Start active scan
      const response = await this.makeZapApiCall('ascan/action/scan/', {
        url: this.config.target,
        contextId: '0',
        recurse: 'true'
      })

      const scanId = response.scan

      // Monitor scan progress
      await this.monitorScanProgress('ascan', scanId)
      
      console.log('Active security scan completed')
    } catch (error) {
      throw new Error(`Active scan failed: ${error}`)
    }
  }

  /**
   * Monitor scan progress
   */
  private async monitorScanProgress(scanType: string, scanId: string): Promise<void> {
    const startTime = Date.now()
    
    while (Date.now() - startTime < this.config.maxScanDuration) {
      try {
        const response = await this.makeZapApiCall(`${scanType}/view/status/`, { scanId })
        const progress = parseInt(response.status)
        
        console.log(`${scanType} scan progress: ${progress}%`)
        
        if (progress >= 100) {
          break
        }
        
        await new Promise(resolve => setTimeout(resolve, 5000))
      } catch (error) {
        console.error(`Error checking ${scanType} scan progress:`, error)
        break
      }
    }
  }

  /**
   * Get scan results and analyze
   */
  async getScanResults(): Promise<ZapScanResults> {
    try {
      console.log('Retrieving scan results...')
      
      // Get alerts
      const alertsResponse = await this.makeZapApiCall('core/view/alerts/', {
        baseurl: this.config.target
      })
      
      const alerts: ZapAlert[] = alertsResponse.alerts || []
      
      // Calculate summary
      const summary = {
        high: alerts.filter(a => a.riskdesc?.toLowerCase().includes('high')).length,
        medium: alerts.filter(a => a.riskdesc?.toLowerCase().includes('medium')).length,
        low: alerts.filter(a => a.riskdesc?.toLowerCase().includes('low')).length,
        informational: alerts.filter(a => a.riskdesc?.toLowerCase().includes('informational')).length,
        total: alerts.length
      }

      // Assess compliance
      const compliance = this.assessCompliance(alerts)

      const results: ZapScanResults = {
        alerts,
        summary,
        scanInfo: {
          startTime: new Date().toISOString(),
          endTime: new Date().toISOString(),
          duration: 0,
          target: this.config.target,
          status: 'completed'
        },
        compliance
      }

      console.log('Scan results summary:', summary)
      return results
    } catch (error) {
      throw new Error(`Failed to get scan results: ${error}`)
    }
  }

  /**
   * Assess compliance with banking and KVKV standards
   */
  private assessCompliance(alerts: ZapAlert[]): { kvkv: boolean; owasp: boolean; banking: boolean } {
    const criticalIssues = alerts.filter(alert => {
      const risk = alert.riskdesc?.toLowerCase()
      return risk?.includes('high') || risk?.includes('critical')
    })

    // Banking-grade compliance requires no high/critical issues
    const banking = criticalIssues.length === 0

    // OWASP compliance - check for specific vulnerability types
    const owaspCritical = alerts.filter(alert => {
      const name = alert.name?.toLowerCase() || ''
      return name.includes('injection') || 
             name.includes('xss') || 
             name.includes('csrf') ||
             name.includes('authentication') ||
             name.includes('authorization')
    })
    
    const owasp = owaspCritical.length === 0

    // KVKV compliance - check for data protection issues
    const kvkvIssues = alerts.filter(alert => {
      const desc = (alert.desc || '').toLowerCase()
      return desc.includes('personal data') ||
             desc.includes('sensitive data') ||
             desc.includes('privacy') ||
             desc.includes('gdpr')
    })
    
    const kvkv = kvkvIssues.length === 0

    return { kvkv, owasp, banking }
  }

  /**
   * Generate security reports
   */
  async generateReports(results: ZapScanResults, outputDir: string): Promise<void> {
    try {
      await fs.mkdir(outputDir, { recursive: true })

      // Generate JSON report
      if (this.config.reportFormats.includes('json')) {
        const jsonReport = JSON.stringify(results, null, 2)
        await fs.writeFile(path.join(outputDir, 'zap-security-report.json'), jsonReport)
      }

      // Generate HTML report
      if (this.config.reportFormats.includes('html')) {
        const htmlReport = await this.makeZapApiCall('core/other/htmlreport/')
        await fs.writeFile(path.join(outputDir, 'zap-security-report.html'), htmlReport)
      }

      // Generate XML report
      if (this.config.reportFormats.includes('xml')) {
        const xmlReport = await this.makeZapApiCall('core/other/xmlreport/')
        await fs.writeFile(path.join(outputDir, 'zap-security-report.xml'), xmlReport)
      }

      // Generate compliance summary
      const complianceSummary = this.generateComplianceSummary(results)
      await fs.writeFile(path.join(outputDir, 'compliance-summary.md'), complianceSummary)

      console.log(`Security reports generated in ${outputDir}`)
    } catch (error) {
      throw new Error(`Failed to generate reports: ${error}`)
    }
  }

  /**
   * Generate compliance summary report
   */
  private generateComplianceSummary(results: ZapScanResults): string {
    const { summary, compliance } = results
    
    return `
# Security Compliance Summary - Task 3.15

**Scan Date:** ${new Date().toISOString()}
**Target:** ${this.config.target}

## Vulnerability Summary

- **High Risk:** ${summary.high}
- **Medium Risk:** ${summary.medium} 
- **Low Risk:** ${summary.low}
- **Informational:** ${summary.informational}
- **Total:** ${summary.total}

## Compliance Status

### Banking-Grade Security
${compliance.banking ? '✅ PASSED' : '❌ FAILED'} - ${compliance.banking ? 'No critical vulnerabilities found' : 'Critical vulnerabilities detected'}

### OWASP Compliance
${compliance.owasp ? '✅ PASSED' : '❌ FAILED'} - ${compliance.owasp ? 'No OWASP Top 10 vulnerabilities found' : 'OWASP vulnerabilities detected'}

### Turkish KVKV Compliance
${compliance.kvkv ? '✅ PASSED' : '❌ FAILED'} - ${compliance.kvkv ? 'No data protection issues found' : 'Data protection issues detected'}

## Critical Findings

${results.alerts
  .filter(alert => alert.riskdesc?.toLowerCase().includes('high'))
  .map(alert => `- **${alert.name}**: ${alert.desc}`)
  .join('\n')}

## Recommendations

${summary.high > 0 ? '1. Address all high-risk vulnerabilities immediately\n' : ''}
${summary.medium > 0 ? '2. Plan remediation for medium-risk vulnerabilities\n' : ''}
${!compliance.banking ? '3. Review banking security standards compliance\n' : ''}
${!compliance.kvkv ? '4. Ensure KVKV data protection compliance\n' : ''}

## Next Steps

1. Review detailed findings in the HTML report
2. Prioritize fixes based on risk level
3. Re-run security scan after remediation
4. Document security improvements

---
*Generated by OWASP ZAP Security Scanner for FreeCad Ultra-Enterprise Testing*
`
  }

  /**
   * Make API call to ZAP
   */
  private async makeZapApiCall(endpoint: string, params: Record<string, string> = {}): Promise<any> {
    const url = new URL(`${this.zapBaseUrl}/${endpoint}`)
    
    // Add API key if configured
    if (this.apiKey) {
      url.searchParams.append('apikey', this.apiKey)
    }
    
    // Add other parameters
    Object.entries(params).forEach(([key, value]) => {
      url.searchParams.append(key, value)
    })

    try {
      const response = await fetch(url.toString())
      
      if (!response.ok) {
        throw new Error(`ZAP API call failed: ${response.status} ${response.statusText}`)
      }
      
      const text = await response.text()
      
      // Try to parse as JSON, fallback to text
      try {
        return JSON.parse(text)
      } catch {
        return text
      }
    } catch (error) {
      throw new Error(`ZAP API call error: ${error}`)
    }
  }

  /**
   * Stop ZAP proxy
   */
  async stopZapProxy(): Promise<void> {
    try {
      await this.makeZapApiCall('core/action/shutdown/')
      console.log('ZAP proxy stopped')
    } catch (error) {
      console.error('Error stopping ZAP:', error)
    }
  }

  /**
   * Run complete security scan
   */
  async runCompleteScan(): Promise<ZapScanResults> {
    try {
      console.log('Starting complete ZAP security scan...')
      
      await this.startZapProxy()
      await this.configureContext()
      await this.spiderScan()
      await this.activeScan()
      
      const results = await this.getScanResults()
      
      // Generate reports
      const outputDir = path.join(process.cwd(), 'test-results', 'security-reports')
      await this.generateReports(results, outputDir)
      
      return results
    } catch (error) {
      throw new Error(`Complete security scan failed: ${error}`)
    }
  }
}

// Export scanner
export default ZapSecurityScanner