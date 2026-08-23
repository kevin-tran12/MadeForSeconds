import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { useSiteStatus } from '../useSiteStatus'
import { API_REACHABLE_EVENT, API_UNREACHABLE_EVENT } from '../../lib/api-client'
import { diagnoseSiteStatus } from '../../lib/site-status'

vi.mock('../../lib/site-status', () => ({
  diagnoseSiteStatus: vi.fn(),
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

  it('does not diagnose on online when nothing is currently wrong', async () => {
    // Regression: calling diagnoseSiteStatus unconditionally on 'online' would
    // probe a perfectly healthy API (no confirmed budget-cap file + a
    // successful no-cors probe = 'refused'), reporting an outage that never
    // happened for an ordinary Wi-Fi blip.
    const { result } = renderHook(() => useSiteStatus())
    expect(result.current).toBeNull()

    act(() => { window.dispatchEvent(new Event('online')) })

    expect(diagnoseSiteStatus).not.toHaveBeenCalled()
    expect(result.current).toBeNull()
  })

  it('re-diagnoses on online when a standing outage is showing', async () => {
    ;(diagnoseSiteStatus as any)
      .mockResolvedValueOnce({ kind: 'unreachable' })
      .mockResolvedValueOnce(null)

    const { result } = renderHook(() => useSiteStatus())

    act(() => { window.dispatchEvent(new Event(API_UNREACHABLE_EVENT)) })
    await waitFor(() => expect(result.current).toEqual({ kind: 'unreachable' }))

    act(() => { window.dispatchEvent(new Event('online')) })

    await waitFor(() => {
      expect(result.current).toBeNull()
    })
    expect(diagnoseSiteStatus).toHaveBeenCalledTimes(2)
  })
})
