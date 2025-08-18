'use client'

import Link from 'next/link'
import React, { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useAuth } from '@/hooks/useAuth'
import { isDevMode } from '@/lib/auth-api'

export function Navbar() {
  const { t } = useTranslation()
  const { isAuthenticated, user, logout, isLoading } = useAuth()
  const [showUserMenu, setShowUserMenu] = useState(false)
  const dev = isDevMode()

  const handleLogout = async () => {
    await logout()
    setShowUserMenu(false)
  }

  const toggleUserMenu = () => {
    setShowUserMenu(!showUserMenu)
  }

  return (
    <nav className="w-full border-b bg-white shadow-sm">
      <div className="max-w-6xl mx-auto px-4 py-2 flex items-center justify-between">
        {/* Logo and Navigation */}
        <div className="flex items-center gap-4">
          <Link className="font-bold text-xl text-blue-600" href="/">
            FreeCAD
          </Link>
          
          {isAuthenticated && (
            <>
              <Link className="text-sm text-gray-700 hover:text-blue-600 hover:underline" href="/jobs">
                {t('nav.jobs')}
              </Link>
              <Link className="text-sm text-gray-700 hover:text-blue-600 hover:underline" href="/assemblies/new">
                {t('nav.assemblies')}
              </Link>
              <Link className="text-sm text-gray-700 hover:text-blue-600 hover:underline" href="/viewer">
                {t('nav.viewer')}
              </Link>
              <Link className="text-sm text-gray-700 hover:text-blue-600 hover:underline" href="/designs/new">
                {t('nav.designs')}
              </Link>
              <Link className="text-sm text-gray-700 hover:text-blue-600 hover:underline" href="/projects/new">
                {t('nav.projects')}
              </Link>
              <Link className="text-sm text-gray-700 hover:text-blue-600 hover:underline" href="/reports">
                {t('nav.reports')}
              </Link>
            </>
          )}
        </div>

        {/* User Menu / Auth Controls */}
        <div className="flex items-center gap-4">
          {/* Dev Mode Indicator */}
          {dev && (
            <span className="text-xs px-2 py-1 rounded bg-yellow-100 text-yellow-800 border border-yellow-300">
              Dev Mod
            </span>
          )}

          {/* Loading State */}
          {isLoading ? (
            <div className="flex items-center space-x-2">
              <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
              <span className="text-sm text-gray-500">Yükleniyor...</span>
            </div>
          ) : isAuthenticated && user ? (
            /* Authenticated User Menu */
            <div className="relative">
              <button
                onClick={toggleUserMenu}
                className="flex items-center space-x-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-full px-3 py-2 transition-colors"
              >
                <div className="w-6 h-6 bg-blue-600 rounded-full flex items-center justify-center text-white text-xs font-medium">
                  {user.firstName?.[0]?.toUpperCase() || user.email[0].toUpperCase()}
                </div>
                <span className="font-medium text-gray-700">
                  {user.firstName ? `${user.firstName} ${user.lastName}` : user.email}
                </span>
                <svg className="w-4 h-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {/* User Menu Dropdown */}
              {showUserMenu && (
                <>
                  {/* Backdrop */}
                  <div 
                    className="fixed inset-0 z-10" 
                    onClick={() => setShowUserMenu(false)}
                  />
                  
                  {/* Menu */}
                  <div className="absolute right-0 mt-2 w-64 bg-white rounded-md shadow-lg border border-gray-200 py-1 z-20">
                    {/* User Info */}
                    <div className="px-4 py-3 border-b border-gray-100">
                      <p className="text-sm font-medium text-gray-900">
                        {user.firstName ? `${user.firstName} ${user.lastName}` : 'Kullanıcı'}
                      </p>
                      <p className="text-xs text-gray-500">{user.email}</p>
                      {user.company && (
                        <p className="text-xs text-gray-500">{user.company}</p>
                      )}
                    </div>

                    {/* Menu Items */}
                    <div className="py-1">
                      <Link
                        href="/settings"
                        className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                        onClick={() => setShowUserMenu(false)}
                      >
                        <div className="flex items-center space-x-2">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          </svg>
                          <span>{t('nav.settings')}</span>
                        </div>
                      </Link>

                      <Link
                        href="/help"
                        className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                        onClick={() => setShowUserMenu(false)}
                      >
                        <div className="flex items-center space-x-2">
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                          </svg>
                          <span>{t('nav.help')}</span>
                        </div>
                      </Link>

                      <div className="border-t border-gray-100 mt-1 pt-1">
                        <button
                          onClick={handleLogout}
                          className="block w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50"
                        >
                          <div className="flex items-center space-x-2">
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                            </svg>
                            <span>{t('auth.session.logout')}</span>
                          </div>
                        </button>
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>
          ) : (
            /* Unauthenticated - Show Login Button */
            <div className="flex items-center space-x-3">
              <Link
                href="/login"
                className="text-sm text-gray-700 hover:text-blue-600 font-medium"
              >
                {t('auth.login.title')}
              </Link>
              <Link
                href="/register"
                className="text-sm bg-blue-600 text-white px-4 py-2 rounded-md hover:bg-blue-700 transition-colors"
              >
                {t('auth.register.title')}
              </Link>
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}


