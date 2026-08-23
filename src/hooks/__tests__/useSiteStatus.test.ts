import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useSiteStatus } from '../useSiteStatus'
import { API_REACHABLE_EVENT, API_UNREACHABLE_EVENT } from '../../lib/api-client'
import { diagnoseSiteStatus, isApiHealthy } from '../../lib/site-status'

vi.mock('../../lib/site-status', () => ({
  diagnoseSiteStatus: vi.fn(),
  isApiHealthy: vi.fn(),
}))

describe('useSiteStatus', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('diagnoses on API_UNREACHABLE_EVENT', async () => {
    ;(diagnoseSiteStatus as any).mockResolvedValue({ kind: 'unreachable' })

    const { result } = renderHook(() => useSiteStatus())
    expect(result.current).toBeNull()

    act(() => { window.dispatchEvent(new Event(API_UNREACHABLE_EVENT)) })

    await waitFor(() => {
      expect(result.current).toEqual({ kind: 'unreachable' })
    })
  })

  it('clears on API_REACHABLE_EVENT without diagnosing', async () => {
    ;(diagnoseSiteStatus as any).mockResolvedValue({ kind: 'unreachable' })
    const { result } = renderHook(() => useSiteStatus())

    act(() => { window.dispatchEvent(new Event(API_UNREACHABLE_EVENT)) })
    await waitFor(() => expect(result.current).not.toBeNull())

    act(() => { window.dispatchEvent(new Event(API_REACHABLE_EVENT)) })
    expect(result.current).toBeNull()
  })

  it('diagnoses on offline even with nothing currently wrong', async () => {
    ;(diagnoseSiteStatus as any).mockResolvedValue({ kind: 'client-offline' })
    const { result } = renderHook(() => useSiteStatus())

    act(() => { window.dispatchEvent(new Event('offline')) })

    await waitFor(() => {
      expect(result.current).toEqual({ kind: 'client-offline' })
    })
  })

  it('does not check health or diagnose on online when nothing is currently wrong', async () => {
    // Regression: calling diagnoseSiteStatus (or even isApiHealthy)
    // unconditionally on 'online' would do real work for an ordinary Wi-Fi
    // blip where nothing was ever wrong.
    const { result } = renderHook(() => useSiteStatus())
    expect(result.current).toBeNull()

    act(() => { window.dispatchEvent(new Event('online')) })

    expect(isApiHealthy).not.toHaveBeenCalled()
    expect(diagnoseSiteStatus).not.toHaveBeenCalled()
    expect(result.current).toBeNull()
  })

  it('clears the banner on online via a health check, not another diagnosis', async () => {
    // diagnoseSiteStatus never resolves to "healthy" — it exists to explain a
    // failure, not detect its absence — so clearing a standing banner on
    // reconnect has to go through isApiHealthy, never a second diagnosis.
    ;(diagnoseSiteStatus as any).mockResolvedValue({ kind: 'unreachable' })
    ;(isApiHealthy as any).mockResolvedValue(true)

    const { result } = renderHook(() => useSiteStatus())

    act(() => { window.dispatchEvent(new Event(API_UNREACHABLE_EVENT)) })
    await waitFor(() => expect(result.current).toEqual({ kind: 'unreachable' }))

    act(() => { window.dispatchEvent(new Event('online')) })

    await waitFor(() => {
      expect(result.current).toBeNull()
    })
    expect(diagnoseSiteStatus).toHaveBeenCalledTimes(1)
  })

  it('falls back to a full diagnosis on online when the API is still unhealthy', async () => {
    ;(diagnoseSiteStatus as any)
      .mockResolvedValueOnce({ kind: 'unreachable' })
      .mockResolvedValueOnce({ kind: 'refused' })
    ;(isApiHealthy as any).mockResolvedValue(false)

    const { result } = renderHook(() => useSiteStatus())

    act(() => { window.dispatchEvent(new Event(API_UNREACHABLE_EVENT)) })
    await waitFor(() => expect(result.current).toEqual({ kind: 'unreachable' }))

    act(() => { window.dispatchEvent(new Event('online')) })

    await waitFor(() => {
      expect(result.current).toEqual({ kind: 'refused' })
    })
  })
})
