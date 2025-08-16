import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import HealthPage from './page'
import { I18nextProvider } from 'react-i18next'
import i18n from '@/lib/i18n/config'
import { ThemeProvider, createTheme } from '@mui/material/styles'
import { server } from '@/tests/testServer'
import { http, HttpResponse } from 'msw'

const theme = createTheme()

const renderWithProviders = (component: React.ReactElement) => {
  return render(
    <I18nextProvider i18n={i18n}>
      <ThemeProvider theme={theme}>
        {component}
      </ThemeProvider>
    </I18nextProvider>
  )
}

describe('Health Page Integration', () => {
  beforeEach(() => {
    // Reset any runtime handlers
    server.resetHandlers()
  })
  
  it('should display healthy status when API returns ok', async () => {
    const mockTimestamp = new Date().toISOString()
    
    server.use(
      http.get('/healthz', () => {
        return HttpResponse.json(
          { status: 'ok', timestamp: mockTimestamp },
          { status: 200 }
        )
      })
    )
    
    renderWithProviders(<HealthPage />)
    
    // Initially should show loading
    expect(screen.getByText('Kontrol Ediliyor...')).toBeInTheDocument()
    
    // Wait for the health check to complete
    await waitFor(() => {
      expect(screen.getByText('Sistem Sağlıklı')).toBeInTheDocument()
    })
    
    // Should display timestamp
    const dateString = new Date(mockTimestamp).toLocaleString('tr-TR')
    expect(screen.getByText(dateString)).toBeInTheDocument()
  })
  
  it('should display error status when API returns error', async () => {
    server.use(
      http.get('/healthz', () => {
        return HttpResponse.json(
          { status: 'error', message: 'Database connection failed' },
          { status: 503 }
        )
      })
    )
    
    renderWithProviders(<HealthPage />)
    
    // Initially should show loading
    expect(screen.getByText('Kontrol Ediliyor...')).toBeInTheDocument()
    
    // Wait for the health check to complete
    await waitFor(() => {
      expect(screen.getByText('Sistem Hatası')).toBeInTheDocument()
    })
  })
  
  it('should display error status when network fails', async () => {
    server.use(
      http.get('/healthz', () => {
        return HttpResponse.error()
      })
    )
    
    renderWithProviders(<HealthPage />)
    
    // Initially should show loading
    expect(screen.getByText('Kontrol Ediliyor...')).toBeInTheDocument()
    
    // Wait for the health check to complete
    await waitFor(() => {
      expect(screen.getByText('Sistem Hatası')).toBeInTheDocument()
    })
  })
})