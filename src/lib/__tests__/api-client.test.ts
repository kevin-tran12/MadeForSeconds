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
