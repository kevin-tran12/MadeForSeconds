import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const STATUS_URL = 'https://storage.googleapis.com/test-status/status.json'
const API_URL = 'https://api.test'

vi.stubEnv('VITE_STATUS_URL', STATUS_URL)
vi.stubEnv('VITE_API_URL', API_URL)

const { diagnoseSiteStatus, isConnectivityError } = await import('../site-status')

/** Route each probe independently so tests read as "what answered what". */
function mockFetch(handlers: {
  status?: () => Promise<Response> | Response
  probe?: () => Promise<Response> | Response
}) {
  const fetchMock = vi.fn((input: string) => {
    if (input === STATUS_URL) {
      if (!handlers.status) return Promise.reject(new TypeError('Failed to fetch'))
      return Promise.resolve(handlers.status())
    }
    if (!handlers.probe) return Promise.reject(new TypeError('Failed to fetch'))
    return Promise.resolve(handlers.probe())
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function jsonResponse(body: unknown, ok = true): Response {
  return { ok, json: async () => body } as Response
}

/**
 * diagnoseSiteStatus() now retries readPublishedStatus with real setTimeout
 * delays before settling on 'refused' — fake timers keep that bounded, so
 * these tests don't actually wait seconds of wall-clock time.
 */
async function diagnoseWithFakeTimers() {
  vi.useFakeTimers()
  try {
    const promise = diagnoseSiteStatus()
    await vi.runAllTimersAsync()
    return await promise
  } finally {
    vi.useRealTimers()
  }
}

beforeEach(() => {
  vi.stubGlobal('navigator', { onLine: true })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('diagnoseSiteStatus', () => {
  it('reports client-offline without probing when the browser says so', async () => {
    vi.stubGlobal('navigator', { onLine: false })
    const fetchMock = mockFetch({})

    expect(await diagnoseSiteStatus()).toEqual({ kind: 'client-offline' })
    // Two doomed round-trips skipped while a visitor waits on a broken page.
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('reports budget-cap when the breaker published one', async () => {
    mockFetch({
      status: () => jsonResponse({ status: 'budget_cap', since: '2026-08-11T06:35:54Z' }),
    })

    expect(await diagnoseSiteStatus()).toEqual({
      kind: 'budget-cap',
      since: '2026-08-11T06:35:54Z',
    })
  })

  it('tolerates a published status with no timestamp', async () => {
    mockFetch({ status: () => jsonResponse({ status: 'budget_cap' }) })

    expect(await diagnoseSiteStatus()).toEqual({ kind: 'budget-cap', since: null })
  })

  it('reports refused when the server answers but nothing confirms why', async () => {
    // 404 is the healthy steady state for the status file — it must never be
    // read as confirmation of a deliberate outage.
    mockFetch({ status: () => jsonResponse({}, false), probe: () => ({}) as Response })

    expect(await diagnoseWithFakeTimers()).toEqual({ kind: 'refused' })
  })

  it('retries the status file briefly and catches one that lands mid-check', async () => {
    // The breaker's IAM revoke and its status.json write are separate calls —
    // a request right after the revoke can lose the race against the write.
    let statusCalls = 0
    mockFetch({
      status: () => {
        statusCalls += 1
        return statusCalls < 3
          ? jsonResponse({}, false) // not written yet
          : jsonResponse({ status: 'budget_cap', since: '2026-08-11T06:35:54Z' })
      },
      probe: () => ({}) as Response,
    })

    expect(await diagnoseWithFakeTimers()).toEqual({
      kind: 'budget-cap',
      since: '2026-08-11T06:35:54Z',
    })
    expect(statusCalls).toBe(3)
  })

  it('gives up after a bounded number of retries and reports refused', async () => {
    let statusCalls = 0
    mockFetch({
      status: () => {
        statusCalls += 1
        return jsonResponse({}, false) // never lands
      },
      probe: () => ({}) as Response,
    })

    expect(await diagnoseWithFakeTimers()).toEqual({ kind: 'refused' })
    // The initial read plus a bounded number of retries, not unbounded polling.
    expect(statusCalls).toBe(4)
  })

  it('reports unreachable when nothing answers at all', async () => {
    mockFetch({})

    expect(await diagnoseSiteStatus()).toEqual({ kind: 'unreachable' })
  })

  it('never claims budget-cap from a malformed status file', async () => {
    mockFetch({ status: () => jsonResponse({ status: 'something-else' }), probe: () => ({}) as Response })

    expect((await diagnoseWithFakeTimers()).kind).toBe('refused')
  })

  it('never claims budget-cap when the status file is unparseable', async () => {
    mockFetch({
      status: () => ({ ok: true, json: async () => { throw new Error('bad json') } }) as Response,
      probe: () => ({}) as Response,
    })

    expect((await diagnoseWithFakeTimers()).kind).toBe('refused')
  })

  it('probes the API with no-cors so an unreadable 403 still counts as answering', async () => {
    const fetchMock = mockFetch({ status: () => jsonResponse({}, false), probe: () => ({}) as Response })

    await diagnoseWithFakeTimers()

    const probeCall = fetchMock.mock.calls.find(([url]) => url !== STATUS_URL)
    expect(probeCall?.[1]).toMatchObject({ mode: 'no-cors' })
  })

  it('reads the status file uncached', async () => {
    const fetchMock = mockFetch({ status: () => jsonResponse({ status: 'budget_cap' }) })

    await diagnoseSiteStatus()

    const statusCall = fetchMock.mock.calls.find(([url]) => url === STATUS_URL)
    expect(statusCall?.[1]).toMatchObject({ cache: 'no-store' })
  })
})

describe('isConnectivityError', () => {
  it('treats a failed fetch as connectivity', () => {
    expect(isConnectivityError(new TypeError('Failed to fetch'))).toBe(true)
  })

  it('leaves ordinary API errors alone', () => {
    // A 404 for a missing recipe must keep its own message.
    expect(isConnectivityError(new Error('Recipe not found'))).toBe(false)
  })
})
