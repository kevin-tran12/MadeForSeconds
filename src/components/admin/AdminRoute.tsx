import { useNavigate, useLocation, Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { LoginModal } from './LoginModal'

export function AdminRoute() {
  const { isAdmin } = useAuth()
  const navigate = useNavigate()
  const { pathname } = useLocation()

  if (!isAdmin) {
    if (pathname !== '/admin') {
      return <Navigate to="/" replace />
    }
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <LoginModal onClose={() => navigate('/')} />
      </div>
    )
  }

  return <Outlet />
}
