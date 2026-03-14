const API_URL = import.meta.env.VITE_API_URL as string

if (!API_URL) {
  throw new Error('Missing VITE_API_URL environment variable')
}

let _getToken: (() => Promise<string | null>) | null = null

/** Called once by AuthContext to wire up token retrieval. */
export function setTokenGetter(fn: () => Promise<string | null>) {
  _getToken = fn
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) ?? {}),
  }

  // Attach auth token if available
  if (_getToken) {
    const token = await _getToken()
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
  }

  // Dev mode: send admin bypass header
  if (import.meta.env.DEV && !headers['Authorization']) {
    headers['X-Dev-Admin'] = 'true'
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error((err as { detail: string }).detail || 'Request failed')
  }

  if (response.status === 204) return undefined as T
  return response.json()
}

/** Specific helper for multipart/form-data uploads. */
export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const headers: Record<string, string> = {}

  if (_getToken) {
    const token = await _getToken()
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
  }

  if (import.meta.env.DEV && !headers['Authorization']) {
    headers['X-Dev-Admin'] = 'true'
  }

  const response = await fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Upload failed' }))
    throw new Error((err as { detail: string }).detail || 'Upload failed')
  }

  return response.json()
}
