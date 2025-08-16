import { create } from 'zustand'
import { devtools, persist } from 'zustand/middleware'

interface User {
  id: string
  name: string
  email: string
  role: string
}

interface AppState {
  // User state
  user: User | null
  isAuthenticated: boolean
  
  // UI state
  sidebarOpen: boolean
  theme: 'light' | 'dark'
  language: 'tr' | 'en'
  
  // Notification state
  notifications: Array<{
    id: string
    type: 'success' | 'error' | 'warning' | 'info'
    message: string
    timestamp: Date
  }>
  
  // Actions
  setUser: (user: User | null) => void
  login: (user: User) => void
  logout: () => void
  toggleSidebar: () => void
  setTheme: (theme: 'light' | 'dark') => void
  setLanguage: (language: 'tr' | 'en') => void
  addNotification: (notification: Omit<AppState['notifications'][0], 'id' | 'timestamp'>) => void
  removeNotification: (id: string) => void
  clearNotifications: () => void
}

export const useAppStore = create<AppState>()(
  devtools(
    persist(
      (set) => ({
        // Initial state
        user: null,
        isAuthenticated: false,
        sidebarOpen: true,
        theme: 'light',
        language: 'tr',
        notifications: [],
        
        // Actions
        setUser: (user) => set({ user, isAuthenticated: !!user }),
        
        login: (user) => set({ 
          user, 
          isAuthenticated: true,
          notifications: [{
            id: Date.now().toString(),
            type: 'success',
            message: `Hoş geldiniz, ${user.name}!`,
            timestamp: new Date()
          }]
        }),
        
        logout: () => set({ 
          user: null, 
          isAuthenticated: false,
          notifications: []
        }),
        
        toggleSidebar: () => set((state) => ({ 
          sidebarOpen: !state.sidebarOpen 
        })),
        
        setTheme: (theme) => set({ theme }),
        
        setLanguage: (language) => set({ language }),
        
        addNotification: (notification) => set((state) => ({
          notifications: [
            ...state.notifications,
            {
              ...notification,
              id: Date.now().toString(),
              timestamp: new Date()
            }
          ]
        })),
        
        removeNotification: (id) => set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== id)
        })),
        
        clearNotifications: () => set({ notifications: [] })
      }),
      {
        name: 'app-storage',
        partialize: (state) => ({
          theme: state.theme,
          language: state.language,
          sidebarOpen: state.sidebarOpen
        })
      }
    )
  )
)

// Selector hooks for better performance
export const useUser = () => useAppStore((state) => state.user)
export const useIsAuthenticated = () => useAppStore((state) => state.isAuthenticated)
export const useSidebarOpen = () => useAppStore((state) => state.sidebarOpen)
export const useTheme = () => useAppStore((state) => state.theme)
export const useLanguage = () => useAppStore((state) => state.language)
export const useNotifications = () => useAppStore((state) => state.notifications)