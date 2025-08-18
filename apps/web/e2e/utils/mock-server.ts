/**
 * Mock Server for Ultra-Enterprise Security Testing - Task 3.15
 * 
 * Provides mock implementations for external services to enable
 * comprehensive testing without external dependencies.
 * Includes OIDC mock server, email service mock, and SMS mock.
 */

import { createServer, IncomingMessage, ServerResponse } from 'http'
import { parse as parseUrl } from 'url'
import { randomBytes, createHash } from 'crypto'

interface MockOidcState {
  state: string
  codeVerifier: string
  nonce: string
  redirectUri: string
}

interface MockUser {
  id: string
  email: string
  name: string
  given_name: string
  family_name: string
  picture?: string
  email_verified: boolean
}

export class MockOidcServer {
  private server: any
  private port: number
  private states: Map<string, MockOidcState> = new Map()
  private codes: Map<string, { user: MockUser; state: string }> = new Map()
  private users: MockUser[] = [
    {
      id: 'mock-user-1',
      email: 'test.user@gmail.com',
      name: 'Test User',
      given_name: 'Test',
      family_name: 'User',
      picture: 'https://lh3.googleusercontent.com/mock-avatar',
      email_verified: true
    },
    {
      id: 'mock-user-2', 
      email: 'admin.user@gmail.com',
      name: 'Admin User',
      given_name: 'Admin',
      family_name: 'User',
      email_verified: true
    }
  ]

  constructor(port: number = 9999) {
    this.port = port
  }

  start(): Promise<void> {
    return new Promise((resolve) => {
      this.server = createServer(this.handleRequest.bind(this))
      this.server.listen(this.port, () => {
        console.log(`Mock OIDC server running on port ${this.port}`)
        resolve()
      })
    })
  }

  stop(): Promise<void> {
    return new Promise((resolve) => {
      if (this.server) {
        this.server.close(() => {
          console.log('Mock OIDC server stopped')
          resolve()
        })
      } else {
        resolve()
      }
    })
  }

  private handleRequest(req: IncomingMessage, res: ServerResponse) {
    const url = parseUrl(req.url || '', true)
    const path = url.pathname
    
    // Set CORS headers
    res.setHeader('Access-Control-Allow-Origin', '*')
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization')
    
    if (req.method === 'OPTIONS') {
      res.writeHead(200)
      res.end()
      return
    }

    try {
      switch (path) {
        case '/.well-known/openid_configuration':
          this.handleOpenIdConfiguration(req, res)
          break
        case '/oauth2/v2/auth':
          this.handleAuthorize(req, res, url.query)
          break
        case '/oauth2/v4/token':
          this.handleToken(req, res)
          break
        case '/oauth2/v1/userinfo':
          this.handleUserInfo(req, res)
          break
        case '/mock/login':
          this.handleMockLogin(req, res, url.query)
          break
        default:
          res.writeHead(404, { 'Content-Type': 'application/json' })
          res.end(JSON.stringify({ error: 'not_found' }))
      }
    } catch (error) {
      console.error('Mock server error:', error)
      res.writeHead(500, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: 'internal_server_error' }))
    }
  }

  private handleOpenIdConfiguration(req: IncomingMessage, res: ServerResponse) {
    const config = {
      issuer: `http://localhost:${this.port}`,
      authorization_endpoint: `http://localhost:${this.port}/oauth2/v2/auth`,
      token_endpoint: `http://localhost:${this.port}/oauth2/v4/token`,
      userinfo_endpoint: `http://localhost:${this.port}/oauth2/v1/userinfo`,
      jwks_uri: `http://localhost:${this.port}/oauth2/v3/certs`,
      response_types_supported: ['code'],
      subject_types_supported: ['public'],
      id_token_signing_alg_values_supported: ['RS256'],
      scopes_supported: ['openid', 'email', 'profile'],
      claims_supported: ['iss', 'sub', 'aud', 'exp', 'iat', 'auth_time', 'nonce', 'email', 'email_verified', 'name', 'given_name', 'family_name', 'picture']
    }
    
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify(config))
  }

  private handleAuthorize(req: IncomingMessage, res: ServerResponse, query: any) {
    const {
      client_id,
      redirect_uri,
      state,
      code_challenge,
      code_challenge_method,
      nonce,
      response_type,
      scope
    } = query

    // Validate required parameters
    if (!client_id || !redirect_uri || !state || !code_challenge || response_type !== 'code') {
      res.writeHead(400, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: 'invalid_request' }))
      return
    }

    // Store PKCE state
    this.states.set(state, {
      state,
      codeVerifier: '', // Will be verified later
      nonce: nonce || '',
      redirectUri: redirect_uri
    })

    // Simulate Google login page
    const loginPageHtml = `
      <!DOCTYPE html>
      <html>
      <head>
        <title>Mock Google Login</title>
        <style>
          body { font-family: Arial, sans-serif; max-width: 400px; margin: 50px auto; padding: 20px; }
          .login-form { border: 1px solid #ddd; padding: 20px; border-radius: 8px; }
          .user-card { border: 1px solid #eee; padding: 10px; margin: 10px 0; cursor: pointer; border-radius: 4px; }
          .user-card:hover { background-color: #f5f5f5; }
          button { background: #4285f4; color: white; border: none; padding: 10px 20px; border-radius: 4px; cursor: pointer; }
          button:hover { background: #3367d6; }
        </style>
      </head>
      <body>
        <div class="login-form">
          <h2>Mock Google Account</h2>
          <p>Select a test user to continue:</p>
          ${this.users.map((user, index) => `
            <div class="user-card" onclick="selectUser('${user.id}')">
              <strong>${user.name}</strong><br>
              <small>${user.email}</small>
            </div>
          `).join('')}
          <script>
            function selectUser(userId) {
              const form = document.createElement('form');
              form.method = 'POST';
              form.action = '/mock/login';
              
              const userInput = document.createElement('input');
              userInput.type = 'hidden';
              userInput.name = 'user_id';
              userInput.value = userId;
              
              const stateInput = document.createElement('input');
              stateInput.type = 'hidden';
              stateInput.name = 'state';
              stateInput.value = '${state}';
              
              form.appendChild(userInput);
              form.appendChild(stateInput);
              document.body.appendChild(form);
              form.submit();
            }
          </script>
        </div>
      </body>
      </html>
    `

    res.writeHead(200, { 'Content-Type': 'text/html' })
    res.end(loginPageHtml)
  }

  private handleMockLogin(req: IncomingMessage, res: ServerResponse, query: any) {
    if (req.method === 'POST') {
      let body = ''
      req.on('data', chunk => body += chunk)
      req.on('end', () => {
        const params = new URLSearchParams(body)
        const userId = params.get('user_id')
        const state = params.get('state')
        
        if (!userId || !state) {
          res.writeHead(400, { 'Content-Type': 'application/json' })
          res.end(JSON.stringify({ error: 'invalid_request' }))
          return
        }

        const user = this.users.find(u => u.id === userId)
        const stateData = this.states.get(state)
        
        if (!user || !stateData) {
          res.writeHead(400, { 'Content-Type': 'application/json' })
          res.end(JSON.stringify({ error: 'invalid_state' }))
          return
        }

        // Generate authorization code
        const code = `mock_code_${randomBytes(16).toString('hex')}`
        this.codes.set(code, { user, state })
        
        // Redirect back to application
        const redirectUrl = `${stateData.redirectUri}?code=${code}&state=${state}`
        res.writeHead(302, { Location: redirectUrl })
        res.end()
      })
    } else {
      res.writeHead(405, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: 'method_not_allowed' }))
    }
  }

  private handleToken(req: IncomingMessage, res: ServerResponse) {
    if (req.method !== 'POST') {
      res.writeHead(405, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: 'method_not_allowed' }))
      return
    }

    let body = ''
    req.on('data', chunk => body += chunk)
    req.on('end', () => {
      const params = new URLSearchParams(body)
      const grantType = params.get('grant_type')
      const code = params.get('code')
      const codeVerifier = params.get('code_verifier')
      const clientId = params.get('client_id')
      
      if (grantType !== 'authorization_code' || !code || !codeVerifier) {
        res.writeHead(400, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ error: 'invalid_request' }))
        return
      }

      const codeData = this.codes.get(code)
      if (!codeData) {
        res.writeHead(400, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ error: 'invalid_grant' }))
        return
      }

      // Consume the code (single use)
      this.codes.delete(code)

      const { user, state } = codeData
      const stateData = this.states.get(state)
      
      if (!stateData) {
        res.writeHead(400, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ error: 'invalid_state' }))
        return
      }

      // Generate tokens
      const accessToken = `mock_access_${randomBytes(32).toString('hex')}`
      const idToken = this.generateMockIdToken(user, clientId, stateData.nonce)
      
      const tokenResponse = {
        access_token: accessToken,
        token_type: 'Bearer',
        expires_in: 3600,
        id_token: idToken,
        scope: 'openid email profile'
      }
      
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify(tokenResponse))
    })
  }

  private handleUserInfo(req: IncomingMessage, res: ServerResponse) {
    const authHeader = req.headers.authorization
    if (!authHeader || !authHeader.startsWith('Bearer ')) {
      res.writeHead(401, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: 'unauthorized' }))
      return
    }

    const accessToken = authHeader.substring(7)
    
    // For mock purposes, extract user info from token
    // In a real implementation, you'd validate the token
    if (!accessToken.startsWith('mock_access_')) {
      res.writeHead(401, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: 'invalid_token' }))
      return
    }

    // Return first user for mock purposes
    const user = this.users[0]
    
    const userInfo = {
      sub: user.id,
      email: user.email,
      email_verified: user.email_verified,
      name: user.name,
      given_name: user.given_name,
      family_name: user.family_name,
      picture: user.picture
    }
    
    res.writeHead(200, { 'Content-Type': 'application/json' })
    res.end(JSON.stringify(userInfo))
  }

  private generateMockIdToken(user: MockUser, clientId: string, nonce: string): string {
    // Mock JWT (not cryptographically signed for testing)
    const header = Buffer.from(JSON.stringify({
      alg: 'RS256',
      typ: 'JWT',
      kid: 'mock-key-id'
    })).toString('base64url')
    
    const payload = Buffer.from(JSON.stringify({
      iss: `http://localhost:${this.port}`,
      sub: user.id,
      aud: clientId,
      exp: Math.floor(Date.now() / 1000) + 3600,
      iat: Math.floor(Date.now() / 1000),
      auth_time: Math.floor(Date.now() / 1000),
      nonce: nonce,
      email: user.email,
      email_verified: user.email_verified,
      name: user.name,
      given_name: user.given_name,
      family_name: user.family_name,
      picture: user.picture
    })).toString('base64url')
    
    const signature = Buffer.from('mock-signature').toString('base64url')
    
    return `${header}.${payload}.${signature}`
  }
}

/**
 * Mock email service for testing magic link flows
 */
export class MockEmailService {
  private emails: Array<{
    to: string
    subject: string
    body: string
    timestamp: Date
    magicLinkToken?: string
  }> = []

  sendEmail(to: string, subject: string, body: string) {
    // Extract magic link token from email body
    const tokenMatch = body.match(/token=([a-zA-Z0-9_-]+)/)
    const magicLinkToken = tokenMatch ? tokenMatch[1] : undefined
    
    this.emails.push({
      to,
      subject,
      body,
      timestamp: new Date(),
      magicLinkToken
    })
    
    console.log(`Mock email sent to ${to}: ${subject}`)
    return Promise.resolve({ messageId: `mock-${Date.now()}` })
  }

  getEmails(email?: string) {
    return email ? this.emails.filter(e => e.to === email) : this.emails
  }

  getLatestMagicLinkToken(email: string): string | undefined {
    const userEmails = this.emails
      .filter(e => e.to === email && e.magicLinkToken)
      .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
    
    return userEmails[0]?.magicLinkToken
  }

  clear() {
    this.emails = []
  }
}

/**
 * Mock SMS service for testing MFA and notifications
 */
export class MockSmsService {
  private messages: Array<{
    to: string
    body: string
    timestamp: Date
    verificationCode?: string
  }> = []

  sendSms(to: string, body: string) {
    // Extract verification code from SMS body
    const codeMatch = body.match(/(\d{6})/)
    const verificationCode = codeMatch ? codeMatch[1] : undefined
    
    this.messages.push({
      to,
      body,
      timestamp: new Date(),
      verificationCode
    })
    
    console.log(`Mock SMS sent to ${to}: ${body}`)
    return Promise.resolve({ messageId: `mock-sms-${Date.now()}` })
  }

  getMessages(phone?: string) {
    return phone ? this.messages.filter(m => m.to === phone) : this.messages
  }

  getLatestVerificationCode(phone: string): string | undefined {
    const userMessages = this.messages
      .filter(m => m.to === phone && m.verificationCode)
      .sort((a, b) => b.timestamp.getTime() - a.timestamp.getTime())
    
    return userMessages[0]?.verificationCode
  }

  clear() {
    this.messages = []
  }
}

// Export mock services
export {
  MockOidcServer,
  MockEmailService,
  MockSmsService
}