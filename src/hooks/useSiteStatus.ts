import { useCallback, useEffect, useRef, useState } from 'react'
import { API_REACHABLE_EVENT, API_UNREACHABLE_EVENT } from '../lib/api-client'
import { diagnoseSiteStatus, type SiteStatus } from '../lib/site-status'

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
      // diagnoseSiteStatus is documented for use only after an actual
      // failure — call it unconditionally here and an ordinary Wi-Fi blip
      // with nothing wrong would probe the (healthy) API, find no confirmed
      // budget-cap file, and report `refused`: a false outage banner for a
      // site that was never down. Only re-check if there's a standing one
      // to clear or re-diagnose.
      if (statusRef.current !== null) void diagnose()
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
