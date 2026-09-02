import { useState, type KeyboardEvent } from 'react'
import { Button } from '../ui/Button'

interface Props {
  disabled: boolean
  streaming: boolean
  onSend: (question: string) => void
  onStop: () => void
  placeholder?: string
}

const MAX_CHARS = 2000

export function Composer({ disabled, streaming, onSend, onStop, placeholder }: Props) {
  const [value, setValue] = useState('')

  function submit() {
    const question = value.trim()
    if (!question || disabled || streaming) return
    onSend(question)
    setValue('')
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="flex items-end gap-2">
      <textarea
        aria-label="Ask the Sous Chef"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        maxLength={MAX_CHARS}
        rows={2}
        disabled={disabled}
        placeholder={placeholder ?? 'Ask about this recipe…'}
        className="flex-1 resize-none rounded-xl border border-card-border bg-card px-3 py-2 text-sm text-content-body outline-none focus:border-brand-border focus:ring-2 focus:ring-primary-100 disabled:opacity-60"
      />
      {streaming ? (
        <Button type="button" variant="secondary" size="md" onClick={onStop}>
          Stop
        </Button>
      ) : (
        <Button type="button" size="md" onClick={submit} disabled={disabled || !value.trim()}>
          Ask
        </Button>
      )}
    </div>
  )
}
