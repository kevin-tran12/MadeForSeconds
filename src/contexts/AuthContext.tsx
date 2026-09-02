import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { initAuth, onAuthChange, loginWithGoogle, logout as authLogout, getToken, type AuthUser } from '../lib/auth'
import { setTokenGetter, clearTotpToken } from '../lib/api-client'
import { meApi } from '../lib/api'
import type { MeResponse } from '../lib/types-assistant'

const DEV_USER_KEY = 'mfs_dev_admin'

type MeState = 'idle' | 'loading' | 'loaded' | 'failed'

interface AuthContextType {
  /** Firebase user (any Google account) — identity only, never authorization. */
  user: AuthUser | null
  /** Backend-verified profile from /api/me; null while signed out or until it loads. */
  me: MeResponse | null
  /** True from the moment a user exists until /api/me has answered (or failed). */
  meLoading: boolean
  /** Decided server-side from ADMIN_EMAILS. In local dev the dev session is the admin. */
  isAdmin: boolean
  isSupporter: boolean
  /** True when this account has visited before — "Welcome back". */
  returning: boolean
  /** First word of the Google display name, for greetings. */
  firstName: string | null
  loginGoogle: () => Promise<void>
  logout: () => void
  devLogin: (password: string) => boolean
  /** Re-fetch /api/me (after linking a donation, saving cooking experience, or a Sous Chef answer). */
  refreshMe: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [me, setMe] = useState<MeResponse | null>(null)
  const [meState, setMeState] = useState<MeState>('idle')

  useEffect(() => {
    if (import.meta.env.DEV) {
      // Wire up token getter for dev mode (no real token needed)
      setTokenGetter(async () => null)

      // Restore dev session from sessionStorage
      if (sessionStorage.getItem(DEV_USER_KEY) === 'true') {
        setUser({ email: 'dev@local', uid: 'dev-admin' } as unknown as AuthUser)
      }
      return
    }

    // Production: use Identity Platform (Firebase Auth)
    initAuth()
    setTokenGetter(getToken)
    const unsubscribe = onAuthChange(setUser)
    return unsubscribe
  }, [])

  const refreshMe = useCallback(async () => {
    if (!user) {
      setMe(null)
      setMeState('idle')
      return
    }
    setMeState('loading')
    try {
      setMe(await meApi.get())
      setMeState('loaded')
    } catch {
      // Signed in with Firebase but the backend rejected or is unreachable:
      // treat as a plain reader with no verified profile.
      setMe(null)
      setMeState('failed')
    }
  }, [user])

  // Every sign-in or sign-out re-fetches the backend-verified profile.
  useEffect(() => {
    void refreshMe()
  }, [refreshMe])

  async function loginGoogle() {
    if (import.meta.env.DEV) return
    await loginWithGoogle()
  }

  function logout() {
    clearTotpToken()
    if (import.meta.env.DEV) {
      sessionStorage.removeItem(DEV_USER_KEY)
      setUser(null)
      return
    }
    authLogout()
  }

  function devLogin(password: string): boolean {
    const expected = import.meta.env.VITE_DEV_ADMIN_PASSWORD
    if (!expected || password !== expected) return false
    sessionStorage.setItem(DEV_USER_KEY, 'true')
    setUser({ email: 'dev@local', uid: 'dev-admin' } as unknown as AuthUser)
    return true
  }

  const meLoading = !!user && (meState === 'idle' || meState === 'loading')
  const displayName = (user as { displayName?: string | null } | null)?.displayName ?? null

  const value: AuthContextType = {
    user,
    me,
    meLoading,
    // Never trusted client-side for anything but rendering: every admin
    // endpoint re-checks ADMIN_EMAILS itself.
    isAdmin: import.meta.env.DEV ? !!user : !!me?.is_admin,
    isSupporter: !!me?.supporter,
    returning: !!me?.returning,
    firstName: displayName ? displayName.trim().split(/\s+/)[0] || null : null,
    loginGoogle,
    logout,
    devLogin,
    refreshMe,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuthContext() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuthContext must be used within AuthProvider')
  return ctx
}
