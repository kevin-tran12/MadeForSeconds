import { useAuthContext } from '../contexts/AuthContext'

// Convenience hook so components don't import AuthContext directly
export function useAuth() {
  return useAuthContext()
}
