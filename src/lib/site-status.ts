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

// The breaker's IAM revoke and its status.json write (terraform/modules/
// cost-controls/billing_function/main.py) are two separate calls, in that
// order. A request that fails right after the revoke can easily lose the
// race against the write — landing a 404 on status.json a moment before it
// exists — and there is no server push to correct it afterwards: nothing
// re-runs diagnoseSiteStatus once it settles, until some other request
// happens to fail again. A short bounded retry here catches the common case
// instead of settling permanently on the less-confident "refused".
//
// The retry timeout is deliberately much shorter than PROBE_TIMEOUT_MS: these
// exist to catch a write landing moments ago, not to wait out a slow GCS. At
// PROBE_TIMEOUT_MS each, three retries could add ~12s on top of the initial
// read before a visitor sees any banner at all — far worse than the race
// they're meant to fix.
const STATUS_RETRY_ATTEMPTS = 3
const STATUS_RETRY_DELAY_MS = 1000
const STATUS_RETRY_TIMEOUT_MS = 1500

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function withTimeout(input: string, init: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(input, { ...init, signal: controller.signal })
  } finally {
    clearTimeout(timer)
  }
}

type PublishedStatusCheck =
  /** The breaker published a cost-cap status. */
  | { kind: 'confirmed'; since: string | null }
  /** GCS answered; no cost-cap status (including a plain 404 — the normal healthy state). */
  | { kind: 'absent' }
  /** The read itself failed or timed out — GCS didn't answer within timeoutMs. */
  | { kind: 'error' }

/**
 * Did the breaker publish a cost-cap status? Distinguishes a definitive "no"
 * (worth retrying — GCS answered fine, the write just isn't there yet) from
 * "couldn't tell" (not worth retrying — GCS itself isn't answering right now,
 * and more attempts at a timeout that already elapsed won't fix that).
 */
async function checkPublishedStatus(timeoutMs: number): Promise<PublishedStatusCheck> {
  if (!STATUS_URL) return { kind: 'error' }
  try {
    const res = await withTimeout(STATUS_URL, { cache: 'no-store' }, timeoutMs)
    if (!res.ok) return { kind: 'absent' }
    const body = (await res.json()) as { status?: string; since?: string }
    return body.status === 'budget_cap' ? { kind: 'confirmed', since: body.since ?? null } : { kind: 'absent' }
  } catch {
    return { kind: 'error' }
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
    await withTimeout(`${API_URL}/api/health`, { mode: 'no-cors', cache: 'no-store' }, PROBE_TIMEOUT_MS)
    return true
  } catch {
    return false
  }
}

/**
 * Is the API actually healthy right now?
 *
 * Unlike serverIsAnswering()'s no-cors probe, this is a normal, CORS-readable
 * fetch — it can tell an actual 200 apart from "something answered", which is
 * exactly what confirming a *recovery* needs. It reads as unhealthy for a real
 * network failure and for a still-tripped breaker (an edge 403 with no CORS
 * headers) alike, which is correct: only a genuinely serving API should clear
 * a standing outage banner.
 */
export async function isApiHealthy(): Promise<boolean> {
  try {
    const res = await withTimeout(`${API_URL}/api/health`, { cache: 'no-store' }, PROBE_TIMEOUT_MS)
    return res.ok
  } catch {
    return false
  }
}

/**
 * Diagnose a failed API request. Call this only after a request has actually
 * failed — it costs at least two network round-trips, and up to a handful
 * more while retrying an unconfirmed refusal (bounded — see
 * STATUS_RETRY_ATTEMPTS/STATUS_RETRY_TIMEOUT_MS above; worst case is one
 * PROBE_TIMEOUT_MS wait plus a few STATUS_RETRY_TIMEOUT_MS ones, never
 * several full-length timeouts stacked). This never resolves to "healthy" —
 * it exists to explain a failure, not to detect its absence. Use isApiHealthy
 * for that.
 */
export async function diagnoseSiteStatus(): Promise<SiteStatus> {
  // navigator.onLine is unreliable when true (it only means "a network exists"),
  // but a false is trustworthy and lets us skip two doomed probes.
  if (typeof navigator !== 'undefined' && navigator.onLine === false) {
    return { kind: 'client-offline' }
  }

  const initial = await checkPublishedStatus(PROBE_TIMEOUT_MS)
  if (initial.kind === 'confirmed') return { kind: 'budget-cap', since: initial.since }

  if (!(await serverIsAnswering())) return { kind: 'unreachable' }

  // Retry only on a confirmed absence (GCS answered; no cost-cap file yet) —
  // that's the write-landed-a-moment-later race this is for. A read that
  // itself failed or timed out means GCS is the one having trouble right
  // now, which more short-timeout attempts at the same unreachable origin
  // won't fix; bail out immediately rather than stacking delay for nothing.
  if (initial.kind === 'absent') {
    for (let attempt = 0; attempt < STATUS_RETRY_ATTEMPTS; attempt++) {
      await sleep(STATUS_RETRY_DELAY_MS)
      const retried = await checkPublishedStatus(STATUS_RETRY_TIMEOUT_MS)
      if (retried.kind === 'confirmed') return { kind: 'budget-cap', since: retried.since }
      if (retried.kind === 'error') break
    }
  }

  return { kind: 'refused' }
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
