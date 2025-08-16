import { describe, it, expect, beforeEach } from 'vitest'
import { useAppStore } from './app-store'

describe('App Store', () => {
  beforeEach(() => {
    // Reset store state before each test
    useAppStore.setState({
      user: null,
      isAuthenticated: false,
      sidebarOpen: true,
      theme: 'light',
      language: 'tr',
      notifications: []
    })
  })
  
  describe('User Management', () => {
    it('should set user and authentication status', () => {
      const testUser = {
        id: '1',
        name: 'Test Kullanıcı',
        email: 'test@example.com',
        role: 'admin'
      }
      
      useAppStore.getState().setUser(testUser)
      
      expect(useAppStore.getState().user).toEqual(testUser)
      expect(useAppStore.getState().isAuthenticated).toBe(true)
    })
    
    it('should handle login', () => {
      const testUser = {
        id: '1',
        name: 'Test Kullanıcı',
        email: 'test@example.com',
        role: 'admin'
      }
      
      useAppStore.getState().login(testUser)
      
      expect(useAppStore.getState().user).toEqual(testUser)
      expect(useAppStore.getState().isAuthenticated).toBe(true)
      expect(useAppStore.getState().notifications).toHaveLength(1)
      expect(useAppStore.getState().notifications[0].type).toBe('success')
    })
    
    it('should handle logout', () => {
      const testUser = {
        id: '1',
        name: 'Test Kullanıcı',
        email: 'test@example.com',
        role: 'admin'
      }
      
      useAppStore.getState().login(testUser)
      useAppStore.getState().logout()
      
      expect(useAppStore.getState().user).toBeNull()
      expect(useAppStore.getState().isAuthenticated).toBe(false)
      expect(useAppStore.getState().notifications).toHaveLength(0)
    })
  })
  
  describe('UI State Management', () => {
    it('should toggle sidebar', () => {
      const initialState = useAppStore.getState().sidebarOpen
      
      useAppStore.getState().toggleSidebar()
      expect(useAppStore.getState().sidebarOpen).toBe(!initialState)
      
      useAppStore.getState().toggleSidebar()
      expect(useAppStore.getState().sidebarOpen).toBe(initialState)
    })
    
    it('should set theme', () => {
      useAppStore.getState().setTheme('dark')
      expect(useAppStore.getState().theme).toBe('dark')
      
      useAppStore.getState().setTheme('light')
      expect(useAppStore.getState().theme).toBe('light')
    })
    
    it('should set language', () => {
      useAppStore.getState().setLanguage('en')
      expect(useAppStore.getState().language).toBe('en')
      
      useAppStore.getState().setLanguage('tr')
      expect(useAppStore.getState().language).toBe('tr')
    })
  })
  
  describe('Notification Management', () => {
    it('should add notification', () => {
      useAppStore.getState().addNotification({
        type: 'info',
        message: 'Test bildirimi'
      })
      
      expect(useAppStore.getState().notifications).toHaveLength(1)
      expect(useAppStore.getState().notifications[0].type).toBe('info')
      expect(useAppStore.getState().notifications[0].message).toBe('Test bildirimi')
      expect(useAppStore.getState().notifications[0].id).toBeDefined()
      expect(useAppStore.getState().notifications[0].timestamp).toBeInstanceOf(Date)
    })
    
    it('should remove notification', () => {
      useAppStore.getState().addNotification({
        type: 'info',
        message: 'Test bildirimi 1'
      })
      useAppStore.getState().addNotification({
        type: 'warning',
        message: 'Test bildirimi 2'
      })
      
      const notifications = useAppStore.getState().notifications
      expect(notifications).toHaveLength(2)
      
      const idToRemove = notifications[0].id
      useAppStore.getState().removeNotification(idToRemove)
      
      expect(useAppStore.getState().notifications).toHaveLength(1)
      expect(useAppStore.getState().notifications[0].message).toBe('Test bildirimi 2')
    })
    
    it('should clear all notifications', () => {
      useAppStore.getState().addNotification({
        type: 'info',
        message: 'Test bildirimi 1'
      })
      useAppStore.getState().addNotification({
        type: 'warning',
        message: 'Test bildirimi 2'
      })
      
      expect(useAppStore.getState().notifications).toHaveLength(2)
      
      useAppStore.getState().clearNotifications()
      
      expect(useAppStore.getState().notifications).toHaveLength(0)
    })
  })
})