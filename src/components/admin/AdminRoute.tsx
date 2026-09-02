import { Link, useNavigate, Outlet } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { LoginModal } from './LoginModal'
import { Button } from '../ui/Button'
import { LoadingSpinner } from '../ui/LoadingSpinner'

export function AdminRoute() {
  const { user, isAdmin, meLoading, logout } = useAuth()
  const navigate = useNavigate()

  if (!user) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <LoginModal onClose={() => navigate('/')} />
      </div>
    )
  }

  // Signed in, but the backend has not yet said whether this account is an
  // admin. Readers can sign in too now, so "signed in" no longer implies it.
  if (meLoading) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <LoadingSpinner />
      </div>
    )
  }

  if (!isAdmin) {
    return (
      <div className="mx-auto max-w-md px-4 py-20 text-center">
        <h1 className="font-display text-2xl font-bold text-content mb-3">This Google account isn't an admin</h1>
        <p className="text-content-muted mb-6">
          You're signed in as <span className="font-semibold text-content-body">{user.email}</span>. Recipes and the
          Sous Chef work as usual; the admin area needs an admin account.
        </p>
        <div className="flex items-center justify-center gap-3">
          <Link
            to="/"
            className="inline-flex rounded-xl bg-cta px-5 py-2.5 text-sm font-semibold text-cta-content shadow-sm hover:bg-cta-hover transition-colors"
          >
            Back home
          </Link>
          <Button variant="ghost" size="sm" onClick={logout}>
            Log out
          </Button>
        </div>
      </div>
    )
  }

  return <Outlet />
}
