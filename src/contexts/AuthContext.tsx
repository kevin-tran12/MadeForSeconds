import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { initAuth, onAuthChange, loginWithGoogle, logout as authLogout, getToken, type AuthUser } from '../lib/auth'
import { setTokenGetter } from '../lib/api-client'

const DEV_USER_KEY = 'mfs_dev_admin'

interface AuthContextType {
  user: AuthUser | null
  isAdmin: boolean
  loginGoogle: () => Promise<void>
  logout: () => void
  devLogin: (password: string) => boolean
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)

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

  async function loginGoogle() {
    if (import.meta.env.DEV) return
    await loginWithGoogle()
  }

  function logout() {
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

  const value: AuthContextType = {
    user,
    isAdmin: !!user,
    loginGoogle,
    logout,
    devLogin,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuthContext() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuthContext must be used within AuthProvider')
  return ctx
}
