import { useMemo, useState } from 'react'
import { Button } from '../ui/Button'
import type { ClarifyAnswer, ClarifyQuestion } from '../../lib/types-assistant'

interface Props {
  questions: ClarifyQuestion[]
  disabled?: boolean
  onSubmit: (answers: ClarifyAnswer[]) => void
}

const ZIP = /^\d{5}(-\d{4})?$/

/**
 * The chef's one round of questions, asked and answered together.
 *
 * A `location` question is only ever a zip code — five digits, nothing else —
 * and the field is built for exactly that, so a reader is never invited to
 * type a street or a city. Blank answers are allowed: the chef answers with
 * stated assumptions rather than asking twice.
 */
export function ClarifyForm({ questions, disabled, onSubmit }: Props) {
  const [values, setValues] = useState<string[]>(() => questions.map(() => ''))

  const badZip = useMemo(
    () => questions.some((q, i) => q.kind === 'location' && values[i].trim() && !ZIP.test(values[i].trim())),
    [questions, values]
  )
  const anyAnswered = values.some((v) => v.trim())

  function submit() {
    if (disabled || badZip || !anyAnswered) return
    onSubmit(questions.map((q, i) => ({ kind: q.kind, text: values[i].trim() })))
  }

  return (
    <form
      className="mt-2 flex flex-col gap-2 rounded-xl border border-card-border bg-card px-3 py-3"
      onSubmit={(e) => {
        e.preventDefault()
        submit()
      }}
    >
      {questions.map((q, i) => (
        <label key={`${q.kind}-${i}`} className="flex flex-col gap-1 text-sm text-content-body">
          <span>{q.text}</span>
          <input
            type="text"
            value={values[i]}
            onChange={(e) => setValues((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))}
            disabled={disabled}
            {...(q.kind === 'location'
              ? { inputMode: 'numeric' as const, maxLength: 10, placeholder: '94110', autoComplete: 'postal-code' }
              : { maxLength: 300 })}
            className="rounded-lg border border-card-border bg-surface px-2.5 py-1.5 text-sm text-content-body outline-none focus:border-brand-border focus:ring-2 focus:ring-primary-100 disabled:opacity-60"
          />
        </label>
      ))}
      {badZip && <p className="text-xs text-danger">A five-digit zip code, please — that's all the chef needs.</p>}
      <div className="flex items-center gap-2">
        <Button type="submit" size="sm" disabled={disabled || badZip || !anyAnswered}>
          Answer
        </Button>
        <span className="text-xs text-content-muted">This one's on the chef — it won't cost you a question.</span>
      </div>
    </form>
  )
}
