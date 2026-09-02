import { useCallback, useEffect, useRef, useState } from 'react'
import { assistantApi } from '../lib/api'
import { ApiError } from '../lib/api-client'
import type { Recipe } from '../lib/types'
import type { UnitSystem } from '../lib/units'
import type { AskDoneEvent, AskErrorCode, AssistantStatus, ChatMessage, QuotaInfo } from '../lib/types-assistant'

export interface SousChefError {
  code: AskErrorCode
  message: string
  supporter?: boolean
  resetsAt?: string
}

const MAX_HISTORY = 8

function newId(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : String(Date.now() + Math.random())
}

/** Translate a failed request into something the drawer can render. */
export function toSousChefError(err: unknown): SousChefError {
  if (err instanceof ApiError) {
    const detail = (err.detail && typeof err.detail === 'object' ? err.detail : {}) as {
      code?: string
      message?: string
      supporter?: boolean
      resets_at?: string
    }
    const known: AskErrorCode[] = [
      'not_configured', 'quota_exhausted', 'spend_cap', 'budget_unavailable', 'invalid_question',
      'prompt_too_long', 'recipe_not_found', 'upstream_busy', 'upstream_error', 'refused',
    ]
    if (err.status === 401 || err.status === 403) {
      return { code: 'sign_in_required', message: 'Sign in with Google to ask the Sous Chef.' }
    }
    if (err.code && (known as string[]).includes(err.code)) {
      return { code: err.code as AskErrorCode, message: err.message, supporter: detail.supporter, resetsAt: detail.resets_at }
    }
    if (err.status === 429) return { code: 'rate_limited', message: 'Easy there — give it a minute and try again.' }
    return { code: 'upstream_error', message: err.message || 'Something went wrong.' }
  }
  if (err instanceof Error && err.name === 'AbortError') {
    return { code: 'upstream_error', message: 'Stopped.' }
  }
  return { code: 'network', message: "Couldn't reach the kitchen. Check your connection and try again." }
}

export function useSousChef(recipe: Recipe, view: { servings: number; unitSystem: UnitSystem }) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [phase, setPhase] = useState<'idle' | 'streaming'>('idle')
  const [status, setStatus] = useState<AssistantStatus | null>(null)
  const [statusLoading, setStatusLoading] = useState(true)
  const [quota, setQuota] = useState<QuotaInfo | null>(null)
  const [error, setError] = useState<SousChefError | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const viewRef = useRef(view)
  viewRef.current = view

  const loadStatus = useCallback(async () => {
    setStatusLoading(true)
    try {
      setStatus(await assistantApi.status())
    } catch {
      setStatus(null)
      setError({ code: 'network', message: "Couldn't reach the kitchen. Check your connection and try again." })
    } finally {
      setStatusLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadStatus()
    return () => abortRef.current?.abort()
  }, [loadStatus])

  const send = useCallback(
    async (rawQuestion: string) => {
      const question = rawQuestion.trim()
      if (!question || phase === 'streaming') return
      setError(null)

      const history = messages
        .filter((m) => !m.pending && !m.refused && m.content.trim())
        .slice(-MAX_HISTORY)
        .map((m) => ({ role: m.role, content: m.content }))
      const userMessage: ChatMessage = { id: newId(), role: 'user', content: question }
      const pendingId = newId()
      setMessages((prev) => [...prev, userMessage, { id: pendingId, role: 'assistant', content: '', pending: true }])
      setPhase('streaming')

      const controller = new AbortController()
      abortRef.current = controller
      let receivedAnything = false

      const patchPending = (patch: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)) =>
        setMessages((prev) =>
          prev.map((m) => (m.id === pendingId ? { ...m, ...(typeof patch === 'function' ? patch(m) : patch) } : m))
        )

      try {
        await assistantApi.ask(
          {
            slug: recipe.slug,
            question,
            history,
            context: { servings: viewRef.current.servings, unit_system: viewRef.current.unitSystem },
          },
          (event, data) => {
            if (event === 'meta') {
              setQuota((data as { quota: QuotaInfo }).quota)
            } else if (event === 'delta') {
              receivedAnything = true
              const text = (data as { text: string }).text
              patchPending((m) => ({ content: m.content + text }))
            } else if (event === 'done') {
              const done = data as AskDoneEvent
              setQuota(done.quota)
              patchPending({ pending: false, truncated: done.truncated, refused: done.refused })
            } else if (event === 'error') {
              const e = data as { code: AskErrorCode; message: string }
              setError({ code: e.code, message: e.message })
              if (e.code === 'refused') {
                patchPending({ pending: false, refused: true, content: e.message })
              } else {
                patchPending({ pending: false })
              }
            }
          },
          controller.signal
        )
      } catch (err) {
        const mapped = toSousChefError(err)
        if (!(err instanceof Error && err.name === 'AbortError')) setError(mapped)
        // Nothing streamed: drop the empty bubble so the question can be retried.
        setMessages((prev) => (receivedAnything ? prev.map((m) => (m.id === pendingId ? { ...m, pending: false } : m)) : prev.filter((m) => m.id !== pendingId)))
      } finally {
        abortRef.current = null
        setPhase('idle')
        setMessages((prev) => prev.map((m) => (m.id === pendingId && m.pending ? { ...m, pending: false } : m)))
      }
    },
    [messages, phase, recipe.slug]
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  const reset = useCallback(() => {
    abortRef.current?.abort()
    setMessages([])
    setError(null)
  }, [])

  const sendFeedback = useCallback(
    async (messageId: string, rating: 'up' | 'down') => {
      const index = messages.findIndex((m) => m.id === messageId)
      if (index < 0) return
      const answer = messages[index]
      const question = [...messages.slice(0, index)].reverse().find((m) => m.role === 'user')
      if (!question || !answer.content.trim()) return
      setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, rated: rating } : m)))
      try {
        await assistantApi.feedback({ slug: recipe.slug, question: question.content, answer: answer.content, rating })
      } catch {
        setMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, rated: undefined } : m)))
      }
    },
    [messages, recipe.slug]
  )

  return { messages, phase, status, statusLoading, quota, error, send, stop, reset, sendFeedback, loadStatus, clearError: () => setError(null) }
}
