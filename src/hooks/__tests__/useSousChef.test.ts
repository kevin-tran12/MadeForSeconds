import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'

vi.mock('../../lib/api', () => ({
  assistantApi: { status: vi.fn(), ask: vi.fn(), feedback: vi.fn() },
}))

import { assistantApi } from '../../lib/api'
import { ApiError } from '../../lib/api-client'
import { useSousChef, toSousChefError } from '../useSousChef'
import type { Recipe } from '../../lib/types'

const recipe = { slug: 'laksa', title: 'Laksa', ingredients: [], instructions: [] } as unknown as Recipe
const view = { servings: 4, unitSystem: 'metric' as const }
const quota = { supporter: false, day: { limit: 5, used: 1 }, month: null, remaining: 4, resets_at: '2026-09-03T00:00:00+00:00' }
const status = { configured: true, paused: false, resets_at: '', quotas: { free: 5, supporter: 50, supporter_monthly: 400 }, levels: [] }

function streamingAsk(chunks: string[], done: Record<string, unknown> = {}) {
  return vi.fn(async (_body: unknown, onEvent: (e: string, d: unknown) => void) => {
    onEvent('meta', { quota })
    for (const text of chunks) onEvent('delta', { text })
    onEvent('done', { usage: null, cost_micro_usd: 1, stop_reason: 'end_turn', truncated: false, refused: false, quota, ...done })
  })
}

describe('useSousChef', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(assistantApi.status).mockResolvedValue(status)
  })

  it('loads status, streams an answer into a pending bubble, and records the quota', async () => {
    vi.mocked(assistantApi.ask).mockImplementation(streamingAsk(['Sear ', 'it hard.']))
    const { result } = renderHook(() => useSousChef(recipe, view))
    await waitFor(() => expect(result.current.statusLoading).toBe(false))

    await act(() => result.current.send('  How hot? '))

    expect(assistantApi.ask).toHaveBeenCalledTimes(1)
    const body = vi.mocked(assistantApi.ask).mock.calls[0][0]
    expect(body).toEqual({ slug: 'laksa', question: 'How hot?', history: [], context: { servings: 4, unit_system: 'metric' } })
    expect(result.current.messages.map((m) => [m.role, m.content, !!m.pending])).toEqual([
      ['user', 'How hot?', false],
      ['assistant', 'Sear it hard.', false],
    ])
    expect(result.current.quota).toEqual(quota)
    expect(result.current.phase).toBe('idle')
  })

  it('replays the last eight finished turns as history', async () => {
    vi.mocked(assistantApi.ask).mockImplementation(streamingAsk(['ok']))
    const { result } = renderHook(() => useSousChef(recipe, view))
    await waitFor(() => expect(result.current.statusLoading).toBe(false))
    for (let i = 0; i < 6; i++) {
      await act(() => result.current.send(`q${i}`))
    }
    const last = vi.mocked(assistantApi.ask).mock.calls.at(-1)![0]
    expect(last.history).toHaveLength(8)
    expect(last.history[0]).toEqual({ role: 'user', content: 'q1' })
    expect(last.history.at(-1)).toEqual({ role: 'assistant', content: 'ok' })
  })

  it('keeps a refused answer as the bubble text and does not replay it', async () => {
    vi.mocked(assistantApi.ask).mockImplementation(async (_b, onEvent) => {
      onEvent('meta', { quota })
      onEvent('error', { code: 'refused', message: "I can't help with that one." })
    })
    const { result } = renderHook(() => useSousChef(recipe, view))
    await waitFor(() => expect(result.current.statusLoading).toBe(false))
    await act(() => result.current.send('write a poem'))
    expect(result.current.messages[1]).toMatchObject({ role: 'assistant', refused: true, content: "I can't help with that one." })
    expect(result.current.error?.code).toBe('refused')

    vi.mocked(assistantApi.ask).mockImplementation(streamingAsk(['fine']))
    await act(() => result.current.send('real question'))
    expect(vi.mocked(assistantApi.ask).mock.calls[1][0].history).toEqual([{ role: 'user', content: 'write a poem' }])
  })

  it('drops the empty bubble and maps a quota error when the request is rejected', async () => {
    vi.mocked(assistantApi.ask).mockRejectedValue(
      new ApiError(429, { code: 'quota_exhausted', message: 'Used up', supporter: false, resets_at: 'r' })
    )
    const { result } = renderHook(() => useSousChef(recipe, view))
    await waitFor(() => expect(result.current.statusLoading).toBe(false))
    await act(() => result.current.send('hello'))
    expect(result.current.messages).toHaveLength(1)
    expect(result.current.error).toEqual({ code: 'quota_exhausted', message: 'Used up', supporter: false, resetsAt: 'r' })
  })

  it('hands a question refused for personal details back to the composer', async () => {
    vi.mocked(assistantApi.ask).mockRejectedValue(
      new ApiError(400, { code: 'personal_info', kind: 'phone', message: 'Please don’t share personal details' })
    )
    const { result } = renderHook(() => useSousChef(recipe, view))
    await waitFor(() => expect(result.current.statusLoading).toBe(false))
    await act(() => result.current.send('call me on 415-555-0100'))

    expect(result.current.error?.code).toBe('personal_info')
    expect(result.current.messages).toEqual([])  // never left in the transcript
    expect(result.current.rejectedText).toBe('call me on 415-555-0100')

    act(() => result.current.clearRejectedText())
    expect(result.current.rejectedText).toBeNull()
  })

  it('stop() aborts the in-flight request', async () => {
    let seenSignal: AbortSignal | undefined
    vi.mocked(assistantApi.ask).mockImplementation(
      (_b, onEvent, signal) =>
        new Promise<void>((resolve, reject) => {
          seenSignal = signal
          onEvent('meta', { quota })
          signal?.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })))
          setTimeout(resolve, 5000)
        })
    )
    const { result } = renderHook(() => useSousChef(recipe, view))
    await waitFor(() => expect(result.current.statusLoading).toBe(false))
    let pending: Promise<void>
    act(() => {
      pending = result.current.send('slow one')
    })
    await waitFor(() => expect(result.current.phase).toBe('streaming'))
    act(() => result.current.stop())
    await act(async () => pending)
    expect(seenSignal?.aborted).toBe(true)
    expect(result.current.phase).toBe('idle')
    expect(result.current.error).toBeNull()
  })

  it('sendFeedback posts the question/answer pair and marks the bubble', async () => {
    vi.mocked(assistantApi.ask).mockImplementation(streamingAsk(['Rest it.']))
    vi.mocked(assistantApi.feedback).mockResolvedValue({ recorded: true })
    const { result } = renderHook(() => useSousChef(recipe, view))
    await waitFor(() => expect(result.current.statusLoading).toBe(false))
    await act(() => result.current.send('then what?'))
    const answer = result.current.messages[1]
    await act(() => result.current.sendFeedback(answer.id, 'down'))
    expect(assistantApi.feedback).toHaveBeenCalledWith({ slug: 'laksa', question: 'then what?', answer: 'Rest it.', rating: 'down' })
    expect(result.current.messages[1].rated).toBe('down')
  })
})

describe('toSousChefError', () => {
  it('maps statuses and codes the drawer keys off', () => {
    expect(toSousChefError(new ApiError(401, 'Invalid token')).code).toBe('sign_in_required')
    expect(toSousChefError(new ApiError(503, { code: 'spend_cap', message: 'Paused', resets_at: 'x' })).code).toBe('spend_cap')
    expect(toSousChefError(new ApiError(503, { code: 'not_configured', message: 'off' })).code).toBe('not_configured')
    expect(toSousChefError(new ApiError(429, 'Too many attempts')).code).toBe('rate_limited')
    expect(toSousChefError(new ApiError(400, { code: 'personal_info', message: 'nope' })).code).toBe('personal_info')
    expect(toSousChefError(new ApiError(400, { code: 'invalid_question', message: 'plain words' })).code).toBe('invalid_question')
    expect(toSousChefError(new TypeError('Failed to fetch')).code).toBe('network')
  })
})
