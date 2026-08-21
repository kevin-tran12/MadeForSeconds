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

    window.addEventListener(API_UNREACHABLE_EVENT, onUnreachable)
    window.addEventListener(API_REACHABLE_EVENT, onReachable)
    // The browser regaining a connection is worth re-checking on its own —
    // the visitor may be sitting on the notice waiting for it to clear.
    window.addEventListener('online', onUnreachable)
    window.addEventListener('offline', onUnreachable)

    return () => {
      window.removeEventListener(API_UNREACHABLE_EVENT, onUnreachable)
      window.removeEventListener(API_REACHABLE_EVENT, onReachable)
      window.removeEventListener('online', onUnreachable)
      window.removeEventListener('offline', onUnreachable)
    }
  }, [diagnose])

  return status
}
