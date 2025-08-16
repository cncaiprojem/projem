import { describe, it, expect } from 'vitest'
import { GET, HEAD } from './route'
import { NextResponse } from 'next/server'

describe('/healthz route', () => {
  describe('GET', () => {
    it('should return status ok with 200 status code', async () => {
      const response = await GET()
      const json = await response.json()
      
      expect(response).toBeInstanceOf(NextResponse)
      expect(response.status).toBe(200)
      expect(json).toHaveProperty('status', 'ok')
      expect(json).toHaveProperty('timestamp')
      expect(new Date(json.timestamp)).toBeInstanceOf(Date)
    })
  })
  
  describe('HEAD', () => {
    it('should return 200 status code with no body', async () => {
      const response = await HEAD()
      
      expect(response).toBeInstanceOf(Response)
      expect(response.status).toBe(200)
      expect(response.body).toBeNull()
    })
  })
})