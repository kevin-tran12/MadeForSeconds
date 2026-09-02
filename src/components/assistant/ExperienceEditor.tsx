import { useState } from 'react'
import { COOKING_LEVELS, type CookingExperience, type CookingLevel } from '../../lib/types-assistant'
import { Button } from '../ui/Button'

interface Props {
  initial: CookingExperience | null
  /** First run: "Skip" saves the default level; later: "Cancel" just closes. */
  firstRun: boolean
  onSave: (level: CookingLevel, notes: string) => Promise<void>
  onDismiss: () => void
}

export function ExperienceEditor({ initial, firstRun, onSave, onDismiss }: Props) {
  const [level, setLevel] = useState<CookingLevel>(initial?.level ?? 'home_cook')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setSaving(true)
    setError(null)
    try {
      await onSave(level, notes.trim())
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h3 className="font-display text-lg font-semibold text-content">
          {firstRun ? 'How do you cook?' : 'Your cooking experience'}
        </h3>
        <p className="mt-1 text-sm text-content-muted">
          The Sous Chef pitches its answers to you — how much to explain, how much to assume. Saved to your
          account; change it any time.
        </p>
      </div>

      <fieldset className="flex flex-col gap-2">
        <legend className="sr-only">Cooking level</legend>
        {COOKING_LEVELS.map((opt) => (
          <label
            key={opt.value}
            className={`flex cursor-pointer items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors ${
              level === opt.value ? 'border-brand-border bg-brand-surface' : 'border-card-border bg-card hover:border-brand-border'
            }`}
          >
            <input
              type="radio"
              name="cooking-level"
              value={opt.value}
              checked={level === opt.value}
              onChange={() => setLevel(opt.value)}
              className="mt-1"
            />
            <span>
              <span className="block text-sm font-semibold text-content">{opt.label}</span>
              <span className="block text-xs text-content-muted">{opt.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      <label className="flex flex-col gap-1">
        <span className="text-sm font-medium text-content-body">Anything the chef should know? (optional)</span>
        <textarea
          aria-label="Cooking notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          maxLength={300}
          rows={2}
          placeholder="e.g. no oven, tiny kitchen, vegetarian, learning knife skills"
          className="resize-none rounded-xl border border-card-border bg-card px-3 py-2 text-sm text-content-body outline-none focus:border-brand-border focus:ring-2 focus:ring-primary-100"
        />
        <span className="text-right text-xs text-content-muted">{notes.length}/300</span>
      </label>

      {error && <p className="text-sm text-danger">{error}</p>}

      <div className="flex gap-2">
        <Button type="button" onClick={save} loading={saving}>
          Save
        </Button>
        <Button type="button" variant="ghost" onClick={onDismiss} disabled={saving}>
          {firstRun ? 'Skip for now' : 'Cancel'}
        </Button>
      </div>
    </div>
  )
}
