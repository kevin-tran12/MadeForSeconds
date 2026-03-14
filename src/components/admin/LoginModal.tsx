import { useState, type FormEvent } from 'react'
import { useAuth } from '../../hooks/useAuth'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'

interface LoginModalProps {
  onClose: () => void
}

export function LoginModal({ onClose }: LoginModalProps) {
  const { devLogin, login } = useAuth()
  const isDev = import.meta.env.DEV
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError('')

    if (isDev) {
      const ok = devLogin(password)
      if (ok) onClose()
      else setError('Incorrect password')
      return
    }

    if (!email) {
      setError('Email is required')
      return
    }

    setLoading(true)
    try {
      await login(email, password)
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

        <form onSubmit={handleSubmit} className="flex flex-col gap-5 p-8">
          {error && (
            <div className="rounded-lg bg-red-50 border border-red-100 px-4 py-3 text-sm text-red-600 font-medium">
              {error}
            </div>
          )}

          {!isDev && (
            <Input
              id="login-email"
              type="email"
              label="Email Address"
              placeholder="admin@madeforseconds.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
            />
          )}
          
          <Input
            id="login-password"
            type="password"
            label="Password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoFocus={isDev}
          />

          <div className="flex flex-col gap-3 pt-2">
            <Button type="submit" size="lg" className="w-full shadow-lg shadow-primary-100" disabled={loading} loading={loading}>
              Login
            </Button>
            <Button type="button" variant="ghost" className="w-full" onClick={onClose}>
              Go back
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
