import { useState, type FormEvent } from 'react'
import { useAuth } from '../../hooks/useAuth'
import { GoogleSignInButton } from '../auth/GoogleSignInButton'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'

interface LoginModalProps {
  onClose: () => void
}

export function LoginModal({ onClose }: LoginModalProps) {
  const { devLogin, loginGoogle } = useAuth()
  const isDev = import.meta.env.DEV
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleDevSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')
    const ok = devLogin(password)
    if (ok) onClose()
    else setError('Incorrect password')
  }

  async function handleGoogleLogin() {
    setError('')
    setLoading(true)
    try {
      await loginGoogle()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm overflow-hidden rounded-2xl bg-white shadow-2xl transition-all animate-in fade-in zoom-in duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="bg-primary-600 px-6 py-8 text-center text-white">
          <h2 className="font-display text-2xl font-bold">Admin Login</h2>
          <p className="mt-1 text-sm text-primary-100 opacity-90">
            Access the recipe management dashboard
          </p>
        </div>

        <div className="flex flex-col gap-5 p-8">
          {error && (
            <div className="rounded-lg bg-red-50 border border-red-100 px-4 py-3 text-sm text-red-600 font-medium">
              {error}
            </div>
          )}

          {isDev ? (
            <form onSubmit={handleDevSubmit} className="flex flex-col gap-5">
              <Input
                id="login-password"
                type="password"
                label="Password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoFocus
              />
              <div className="flex flex-col gap-3 pt-2">
                <Button type="submit" size="lg" className="w-full shadow-lg shadow-primary-100">
                  Login
                </Button>
                <Button type="button" variant="ghost" className="w-full" onClick={onClose}>
                  Go back
                </Button>
              </div>
            </form>
          ) : (
            <div className="flex flex-col gap-3 pt-2">
              <GoogleSignInButton onClick={handleGoogleLogin} loading={loading} />
              <Button type="button" variant="ghost" className="w-full" onClick={onClose}>
                Go back
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
