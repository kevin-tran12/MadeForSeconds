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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        className="w-full max-w-sm rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-1 font-display text-xl font-bold text-gray-900">
          {isDev ? 'Local admin login' : 'Admin login'}
        </h2>
        <p className="mb-4 text-sm text-gray-500">
          {isDev ? 'Dev environment \u2014 enter your VITE_DEV_ADMIN_PASSWORD' : 'Sign in with your admin account'}
        </p>
        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {!isDev && (
            <Input
              id="login-email"
              type="email"
              label="Email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
            />
          )}
          <Input
            id="login-password"
            type="password"
            label="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            error={error}
            autoFocus={isDev}
          />
          <div className="flex gap-2">
            <Button type="submit" className="flex-1" disabled={loading}>
              {loading ? 'Signing in\u2026' : 'Login'}
            </Button>
            <Button type="button" variant="ghost" onClick={onClose}>
              Cancel
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}
