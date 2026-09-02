import { parseSse } from './sse'

const API_URL = import.meta.env.VITE_API_URL as string

if (!API_URL) {
  throw new Error('Missing VITE_API_URL environment variable')
}

/** Fired whenever a request reaches a server at all, even a non-2xx response. */
export const API_REACHABLE_EVENT = 'api-reachable'
/** Fired when `fetch` itself rejects — no response came back at all. */
export const API_UNREACHABLE_EVENT = 'api-unreachable'

/**
 * Wraps `fetch` to report connectivity on the way past, for useSiteStatus to
 * pick up. A thrown response body (4xx/5xx) still means the server answered —
 * only a rejected fetch() itself (network failure, DNS, a CORS-opaque refusal)
 * counts as unreachable.
 */
async function fetchWithConnectivitySignal(input: string, init: RequestInit): Promise<Response> {
  try {
    const response = await fetch(input, init)
    window.dispatchEvent(new Event(API_REACHABLE_EVENT))
    return response
  } catch (error) {
    window.dispatchEvent(new Event(API_UNREACHABLE_EVENT))
    throw error
  }
}

let _getToken: (() => Promise<string | null>) | null = null

/** Called once by AuthContext to wire up token retrieval. */
export function setTokenGetter(fn: () => Promise<string | null>) {
  _getToken = fn
}

const TOTP_SESSION_KEY = 'mfs_totp_session'

export function setTotpToken(token: string) {
  sessionStorage.setItem(TOTP_SESSION_KEY, token)
}

export function getTotpToken(): string | null {
  return sessionStorage.getItem(TOTP_SESSION_KEY)
}

export function clearTotpToken() {
  sessionStorage.removeItem(TOTP_SESSION_KEY)
}

/**
 * A non-2xx response. `message` is the backend's `detail` when it is a plain
 * string (every pre-existing endpoint), or its `message` field when `detail`
 * is an object — the Sous Chef endpoints return `{code, message, ...}` so the
 * UI can key off `code`.
 */
export class ApiError extends Error {
  status: number
  code?: string
  detail: unknown

  constructor(status: number, detail: unknown) {
    const obj = detail && typeof detail === 'object' ? (detail as { code?: string; message?: string }) : null
    super(typeof detail === 'string' ? detail : obj?.message || 'Request failed')
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    this.code = obj?.code
  }
}

/** Auth (Firebase token or the dev bypass) and TOTP headers, plus whatever the caller adds. */
async function buildHeaders(extra: Record<string, string> = {}): Promise<Record<string, string>> {
  const headers: Record<string, string> = { ...extra }

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

  // Attach TOTP session token if available
  const totpToken = getTotpToken()
  if (totpToken) {
    headers['X-TOTP-Session'] = totpToken
  }

  return headers
}

async function throwForStatus(response: Response, fallback: string): Promise<never> {
  // If the TOTP session expired, clear the stored token and signal TotpGate
  // to drop back to the verify screen instead of showing a cryptic 403 error.
  if (response.status === 403 && getTotpToken()) {
    clearTotpToken()
    window.dispatchEvent(new Event('totp-session-expired'))
  }
  const err = await response.json().catch(() => ({ detail: fallback }))
  const detail = (err as { detail?: unknown }).detail
  throw new ApiError(response.status, detail === undefined || detail === null ? fallback : detail)
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = await buildHeaders({
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) ?? {}),
  })

  const response = await fetchWithConnectivitySignal(`${API_URL}${path}`, {
    ...options,
    headers,
  })

  if (!response.ok) {
    await throwForStatus(response, 'Request failed')
  }

  if (response.status === 204) return undefined as T
  return response.json()
}

/** Specific helper for multipart/form-data uploads. */
export async function apiUpload<T>(path: string, formData: FormData): Promise<T> {
  const headers = await buildHeaders()

  const response = await fetchWithConnectivitySignal(`${API_URL}${path}`, {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: 'Upload failed' }))
    throw new ApiError(response.status, (err as { detail?: unknown }).detail ?? 'Upload failed')
  }

  return response.json()
}

/**
 * POST a JSON body and consume a Server-Sent Events response. `onEvent`
 * receives each event's name and its JSON-parsed data (or the raw string when
 * it is not JSON). Non-2xx responses throw ApiError before any event fires;
 * an aborted signal rejects with the fetch AbortError.
 */
export async function apiStream(
  path: string,
  body: unknown,
  onEvent: (event: string, data: unknown) => void,
  signal?: AbortSignal
): Promise<void> {
  const headers = await buildHeaders({
    'Content-Type': 'application/json',
    Accept: 'text/event-stream',
  })

  const response = await fetchWithConnectivitySignal(`${API_URL}${path}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })

  if (!response.ok) {
    await throwForStatus(response, 'Request failed')
  }
  if (!response.body) {
    throw new ApiError(response.status, 'Empty response')
  }

  await parseSse(response.body, (event, data) => {
    let parsed: unknown = data
    try {
      parsed = JSON.parse(data)
    } catch {
      // not JSON — hand the raw string through
    }
    onEvent(event, parsed)
  })
}
