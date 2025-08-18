/**
 * Enhanced Authentication Module
 * Integrates with ultra-enterprise auth system (Tasks 3.1-3.12)
 */

import { authAPI, isDevMode } from './auth-api'
import { tokenManager } from './auth-api'

// Legacy dev login function for backward compatibility
export async function devLoginOnce() {
  if (typeof window === 'undefined') return;
  if (!isDevMode()) return;
  if (localStorage.getItem('devAuthed') === 'true') return;
  
  const devUser = process.env.NEXT_PUBLIC_DEV_USER || 'dev@local';
  try {
    const response = await authAPI.devLogin(devUser);
    if (response.access_token) {
      tokenManager.setToken(response.access_token);
      localStorage.setItem('devAuthed', 'true');
    }
  } catch (error) {
    console.warn('Dev login failed:', error);
  }
}

// Enhanced authentication utilities
export async function getCurrentUser() {
  try {
    const response = await authAPI.getCurrentUser();
    return response.user || null;
  } catch (error) {
    return null;
  }
}

export async function isAuthenticated(): Promise<boolean> {
  try {
    const sessionInfo = await authAPI.getSessionInfo();
    return sessionInfo.is_authenticated;
  } catch (error) {
    return false;
  }
}

export async function logout() {
  try {
    await authAPI.logout();
    tokenManager.clearToken();
    if (typeof window !== 'undefined') {
      localStorage.removeItem('devAuthed');
    }
  } catch (error) {
    // Always clear local state even if API call fails
    tokenManager.clearToken();
    if (typeof window !== 'undefined') {
      localStorage.removeItem('devAuthed');
    }
  }
}

// Session management
export async function extendSession() {
  try {
    return await authAPI.extendSession();
  } catch (error) {
    throw error;
  }
}

export async function refreshToken() {
  try {
    const response = await authAPI.refreshToken();
    if (response.access_token) {
      tokenManager.setToken(response.access_token);
    }
    return response;
  } catch (error) {
    throw error;
  }
}


