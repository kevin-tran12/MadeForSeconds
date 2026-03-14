import { useNavigate, Outlet } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { LoginModal } from './LoginModal'

export function AdminRoute() {
  const { isAdmin } = useAuth()
  const navigate = useNavigate()

  if (!isAdmin) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <LoginModal onClose={() => navigate('/')} />
      </div>
    )
  }

  return <Outlet />
}
