/**
 * Works out *why* the API is unreachable, so the UI can say something true
 * instead of showing a raw "Failed to fetch".
 *
 * The hard constraint: when the budget breaker trips it removes `allUsers` from
 * the backend's Cloud Run invoker binding, and Cloud Run then rejects at the
 * edge — before our FastAPI app, so the 403 carries no CORS headers. The browser
 * cannot read that status; `fetch` just rejects, identically to being offline.
 *
 * Hence two extra signals:
 *
 *   1. status.json in a public GCS bucket, written by the breaker on trip and
 *      deleted on reset. GCS stays up when Cloud Run is refusing, so this is the
 *      only source that can confirm the outage was deliberate. Absence proves
 *      nothing (the breaker may have failed to write it), so we only ever use it
 *      to *upgrade* the message, never to claim a real outage is intentional.
 *   2. A `mode: 'no-cors'` probe, which resolves opaquely for any HTTP response
 *      and rejects only on genuine network failure. That separates "server is up
 *      and refusing us" from "cannot reach the server at all".
 */

export type SiteStatus =
  /** The browser reports no network. Their problem, not ours. */
  | { kind: 'client-offline' }
  /** Confirmed deliberate: the breaker published a cost-cap status. */
  | { kind: 'budget-cap'; since: string | null }
  /** Nothing answered. GCP down, DNS, or a captive portal. */
  | { kind: 'unreachable' }
  /** Something answered but refused us, and nothing confirmed why. */
  | { kind: 'refused' }

const STATUS_URL = import.meta.env.VITE_STATUS_URL as string | undefined
const API_URL = import.meta.env.VITE_API_URL as string

/** Fail fast — this runs while a visitor is already staring at a broken page. */
const PROBE_TIMEOUT_MS = 4000

async function withTimeout(input: string, init: RequestInit): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), PROBE_TIMEOUT_MS)
  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

/**
 * Did the breaker publish a cost-cap status?
 *
 * Returns null for "cannot confirm" — including a 404, which is the normal
 * healthy state. Only a positive, well-formed answer counts.
 */
async function readPublishedStatus(): Promise<{ since: string | null } | null> {
  if (!STATUS_URL) return null
  try {
    const res = await withTimeout(STATUS_URL, { cache: 'no-store' })
    if (!res.ok) return null
    const body = (await res.json()) as { status?: string; since?: string }
    return body.status === 'budget_cap' ? { since: body.since ?? null } : null
  } catch {
    return null
  }
}

/**
 * Is anything answering at the API origin?
 *
 * `no-cors` gives an opaque response we cannot read, but resolving at all proves
 * a server responded — which is exactly the distinction we need, since the
 * breaker's 403 is unreadable for CORS reasons rather than absent.
 */
async function serverIsAnswering(): Promise<boolean> {
  try {
    await withTimeout(`${API_URL}/api/health`, { mode: 'no-cors', cache: 'no-store' })
    return true
  } catch {
    return false
  }
}

/**
 * Diagnose a failed API request. Call this only after a request has actually
 * failed — it costs two network round-trips.
 */
export async function diagnoseSiteStatus(): Promise<SiteStatus> {
  // navigator.onLine is unreliable when true (it only means "a network exists"),
  // but a false is trustworthy and lets us skip two doomed probes.
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return { kind: 'client-offline' }
  }

  const published = await readPublishedStatus()
  if (published) return { kind: 'budget-cap', since: published.since }

  return (await serverIsAnswering()) ? { kind: 'refused' } : { kind: 'unreachable' }
}

/**
 * Is this error the kind worth diagnosing?
 *
 * A failed fetch surfaces as TypeError; anything the API answered with in a
 * readable way (a 404 for a missing recipe, say) is a normal application error
 * and must keep its own message.
 */
export function isConnectivityError(error: unknown): boolean {
  return error instanceof TypeError
}
