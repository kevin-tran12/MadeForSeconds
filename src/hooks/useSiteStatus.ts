import { useCallback, useEffect, useRef, useState } from 'react'
import { API_REACHABLE_EVENT, API_UNREACHABLE_EVENT } from '../lib/api-client'
import { diagnoseSiteStatus, isApiHealthy, type SiteStatus } from '../lib/site-status'

/**
 * Watches for API connectivity failures and works out why, so the UI can
 * explain a deliberate cost-cap shutdown rather than showing "Failed to fetch".
 *
 * Returns null while everything is fine.
 */
export function useSiteStatus(): SiteStatus | null {
  const [status, setStatus] = useState<SiteStatus | null>(null)
  // Several requests fail together when the API goes down (recipes, categories,
  // page content). Without this, each would kick off its own pair of probes.
  const diagnosing = useRef(false)
  // Read inside the 'online' handler below instead of closing over `status` —
  // the effect registers its listeners once ([diagnose] deps), so a plain
  // closure would see whatever `status` was on mount, not the current value.
  const statusRef = useRef<SiteStatus | null>(null)
  statusRef.current = status

  const diagnose = useCallback(async () => {
    if (diagnosing.current) return
    diagnosing.current = true
    try {
      setStatus(await diagnoseSiteStatus())
    } finally {
      diagnosing.current = false
    }
  }, [])

  useEffect(() => {
    const onUnreachable = () => { void diagnose() }
    const onReachable = () => setStatus(null)
    const onOnline = () => {
      // Only re-check if there's a standing banner — an ordinary Wi-Fi blip
      // with nothing wrong must not manufacture one (see the diagnose guard
      // below for what happens if this ran unconditionally).
      if (statusRef.current === null) return
      void (async () => {
        // diagnoseSiteStatus never resolves to "healthy" — it exists to
        // explain a failure, not detect its absence, so calling it here
        // could only ever re-diagnose a NEW reason to still be broken, never
        // clear a banner that no longer applies. Confirm real recovery with
        // a normal, CORS-readable health check first; only fall back to a
        // full diagnosis if that also fails.
        if (await isApiHealthy()) {
          setStatus(null)
        } else {
          void diagnose()
        }
      })()
    }

    window.addEventListener(API_UNREACHABLE_EVENT, onUnreachable)
    window.addEventListener(API_REACHABLE_EVENT, onReachable)
    window.addEventListener('online', onOnline)
    // Going offline is always worth a fresh diagnosis — diagnoseSiteStatus's
    // own navigator.onLine check short-circuits straight to `client-offline`
    // without probing anything, so there's no equivalent false-positive risk.
    window.addEventListener('offline', onUnreachable)

    return () => {
      window.removeEventListener(API_UNREACHABLE_EVENT, onUnreachable)
      window.removeEventListener(API_REACHABLE_EVENT, onReachable)
      window.removeEventListener('online', onOnline)
      window.removeEventListener('offline', onUnreachable)
    }
  }, [diagnose])

  return status
}
