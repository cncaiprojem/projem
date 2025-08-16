'use client'

import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Container, Paper, Typography, Box, Chip, CircularProgress } from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'

export default function HealthPage() {
  const { t } = useTranslation()
  const [status, setStatus] = useState<'loading' | 'ok' | 'error'>('loading')
  const [timestamp, setTimestamp] = useState<string>('')
  
  useEffect(() => {
    checkHealth()
  }, [])
  
  async function checkHealth() {
    try {
      const response = await fetch('/healthz')
      const data = await response.json()
      
      if (response.ok && data.status === 'ok') {
        setStatus('ok')
        setTimestamp(data.timestamp)
      } else {
        setStatus('error')
      }
    } catch (error) {
      console.error('Health check failed:', error)
      setStatus('error')
    }
  }
  
  return (
    <Container maxWidth="sm" sx={{ mt: 4 }}>
      <Paper elevation={3} sx={{ p: 4 }}>
        <Typography variant="h4" gutterBottom align="center">
          {t('health.status')}
        </Typography>
        
        <Box display="flex" justifyContent="center" alignItems="center" mt={3} mb={2}>
          {status === 'loading' && (
            <>
              <CircularProgress size={24} sx={{ mr: 1 }} />
              <Typography variant="body1">{t('health.checking')}</Typography>
            </>
          )}
          
          {status === 'ok' && (
            <Chip
              icon={<CheckCircleIcon />}
              label={t('health.ok')}
              color="success"
              size="large"
            />
          )}
          
          {status === 'error' && (
            <Chip
              icon={<ErrorIcon />}
              label={t('health.error')}
              color="error"
              size="large"
            />
          )}
        </Box>
        
        {timestamp && (
          <Typography variant="caption" display="block" align="center" color="text.secondary">
            {new Date(timestamp).toLocaleString('tr-TR')}
          </Typography>
        )}
      </Paper>
    </Container>
  )
}