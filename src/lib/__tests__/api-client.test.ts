import { describe, it, expect, vi, beforeEach } from 'vitest'
import { apiFetch, setTokenGetter, setTotpToken } from '../api-client'

// Mock global fetch
global.fetch = vi.fn()

describe('api-client', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    setTokenGetter(async () => null)
  })

  it('apiFetch injects Content-Type by default', async () => {
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({ data: 'ok' }),
    })

    await apiFetch('/test')
    
    expect(global.fetch).toHaveBeenCalledWith(
      expect.stringContaining('/test'),
      expect.objectContaining({
        headers: expect.objectContaining({
          'Content-Type': 'application/json',
        }),
      })
    )
  })

  it('apiFetch injects Authorization header from token getter', async () => {
    setTokenGetter(async () => 'test-token')
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    })

    await apiFetch('/test')
    
    const call = (global.fetch as any).mock.calls[0]
    const headers = call[1].headers
    expect(headers['Authorization']).toBe('Bearer test-token')
  })

  it('apiFetch injects X-TOTP-Session if token exists', async () => {
    setTotpToken('totp-token')
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve({}),
    })

    await apiFetch('/test')
    
    const call = (global.fetch as any).mock.calls[0]
    const headers = call[1].headers
    expect(headers['X-TOTP-Session']).toBe('totp-token')
  })

  it('apiFetch clears TOTP token and dispatches event on 403', async () => {
    setTotpToken('expired-token')
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ detail: 'TOTP required' }),
    })

    await expect(apiFetch('/test')).rejects.toThrow('TOTP required')
    
    expect(sessionStorage.getItem('mfs_totp_session')).toBeNull()
    expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({ type: 'totp-session-expired' }))
  })
})

// ─── apiStream / ApiError ───────────────────────────────────────────────────

import { apiStream, ApiError } from '../api-client'

function sseBody(text: string): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode(text))
      controller.close()
    },
  })
}

describe('apiStream', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    setTokenGetter(async () => 'reader-token')
  })

  it('POSTs JSON with the auth header and Accept: text/event-stream, then dispatches parsed events', async () => {
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: true,
      status: 200,
      body: sseBody('event: meta\ndata: {"quota":{"remaining":4}}\n\nevent: delta\ndata: {"text":"Hi"}\n\nevent: done\ndata: {"refused":false}\n\n'),
    })
    const events: [string, unknown][] = []
    await apiStream('/api/assistant/ask', { slug: 'x' }, (e, d) => events.push([e, d]))

    const [url, init] = (global.fetch as any).mock.calls[0]
    expect(url).toContain('/api/assistant/ask')
    expect(init.method).toBe('POST')
    expect(init.body).toBe('{"slug":"x"}')
    expect(init.headers['Authorization']).toBe('Bearer reader-token')
    expect(init.headers['Accept']).toBe('text/event-stream')
    expect(events).toEqual([
      ['meta', { quota: { remaining: 4 } }],
      ['delta', { text: 'Hi' }],
      ['done', { refused: false }],
    ])
  })

  it('throws an ApiError carrying the backend code on a non-2xx before any event', async () => {
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 429,
      json: () => Promise.resolve({ detail: { code: 'quota_exhausted', message: 'Used up', supporter: false } }),
    })
    const onEvent = vi.fn()
    await expect(apiStream('/api/assistant/ask', {}, onEvent)).rejects.toMatchObject({
      name: 'ApiError',
      status: 429,
      code: 'quota_exhausted',
      message: 'Used up',
    })
    expect(onEvent).not.toHaveBeenCalled()
  })

  it('apiFetch keeps string details as the message and exposes the status', async () => {
    ;(global.fetch as any).mockResolvedValueOnce({
      ok: false,
      status: 404,
      json: () => Promise.resolve({ detail: 'Recipe not found' }),
    })
    const err = await apiFetch('/api/recipes/ghost').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.message).toBe('Recipe not found')
    expect(err.status).toBe(404)
    expect(err.code).toBeUndefined()
  })
})
