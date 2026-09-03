import { useEffect, useRef } from 'react'
import { ClarifyForm } from './ClarifyForm'
import type { ChatMessage, ClarifyAnswer, ClarifyQuestion } from '../../lib/types-assistant'

interface Props {
  messages: ChatMessage[]
  onRate: (messageId: string, rating: 'up' | 'down') => void
  onClarify?: (questions: ClarifyQuestion[], answers: ClarifyAnswer[]) => void
  /** What the chef is doing before any text arrives, e.g. "Checking sources…". */
  activity?: string | null
}

/** Plain-text bubbles. Never markdown or HTML: model output is rendered as text only. */
export function MessageList({ messages, onRate, onClarify, activity }: Props) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // Guarded: jsdom (unit tests) has no scrollIntoView.
    if (typeof endRef.current?.scrollIntoView === 'function') {
      endRef.current.scrollIntoView({ block: 'end' })
    }
  }, [messages])

  return (
    <div className="flex flex-col gap-3" role="log" aria-live="polite" aria-label="Sous Chef conversation">
      {messages.map((m) =>
        m.role === 'user' ? (
          <div key={m.id} className="ml-8 self-end rounded-2xl rounded-br-sm bg-primary-600 px-4 py-2.5 text-sm text-on-brand whitespace-pre-wrap">
            {m.content}
          </div>
        ) : (
          <div key={m.id} className="mr-8 self-start">
            <div className="rounded-2xl rounded-bl-sm bg-surface-dark px-4 py-2.5 text-sm text-content-body whitespace-pre-wrap">
              {m.content}
              {m.pending &&
                (activity ? (
                  <span className="text-content-muted">{activity}</span>
                ) : (
                  <span className="ml-1 inline-block animate-pulse" aria-label="Thinking">
                    ▍
                  </span>
                ))}
            </div>
            {m.truncated && (
              <p className="mt-1 px-1 text-xs text-content-muted">…that got cut short — ask me to continue.</p>
            )}
            {m.sources?.length ? (
              <div className="mt-1 px-1 text-xs text-content-muted">
                <span className="font-medium">Sources</span>
                <ul className="mt-0.5 flex flex-col gap-0.5">
                  {m.sources.map((s) => (
                    <li key={s.url}>
                      <a
                        href={s.url}
                        target="_blank"
                        rel="noopener nofollow"
                        className="underline decoration-dotted underline-offset-2 hover:text-brand"
                      >
                        {s.title}
                      </a>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {m.clarify?.length && onClarify ? (
              <ClarifyForm questions={m.clarify} onSubmit={(answers) => onClarify(m.clarify!, answers)} />
            ) : null}
            {!m.pending && !m.refused && !m.clarify?.length && m.content.trim() && (
              <div className="mt-1 flex items-center gap-1 px-1">
                <button
                  type="button"
                  onClick={() => onRate(m.id, 'up')}
                  disabled={!!m.rated}
                  aria-label="Helpful"
                  aria-pressed={m.rated === 'up'}
                  className={`rounded p-1 text-xs transition-colors hover:bg-brand-surface ${m.rated === 'up' ? 'text-brand' : 'text-content-muted'} disabled:cursor-default`}
                >
                  👍
                </button>
                <button
                  type="button"
                  onClick={() => onRate(m.id, 'down')}
                  disabled={!!m.rated}
                  aria-label="Not helpful"
                  aria-pressed={m.rated === 'down'}
                  className={`rounded p-1 text-xs transition-colors hover:bg-brand-surface ${m.rated === 'down' ? 'text-brand' : 'text-content-muted'} disabled:cursor-default`}
                >
                  👎
                </button>
                {m.rated && <span className="text-xs text-content-muted">Thanks — that helps the chef.</span>}
              </div>
            )}
          </div>
        )
      )}
      <div ref={endRef} />
    </div>
  )
}
