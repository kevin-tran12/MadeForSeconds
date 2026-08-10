import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { subscriberApi } from '../lib/api'

export function SupportSuccessPage() {
  const [searchParams] = useSearchParams()
  const sessionId = searchParams.get('session_id')

  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sessionInfo, setSessionInfo] = useState<{
    email: string
    payment_type: string
    amount_cents: number
    already_set_up: boolean
  } | null>(null)

  const [displayName, setDisplayName] = useState('')
  const [note, setNote] = useState('')
  const [noteIsPublic, setNoteIsPublic] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [skipped, setSkipped] = useState(false)

  useEffect(() => {
    if (!sessionId) {
      setError('No session found. If you just donated, please check your email for confirmation.')
      setLoading(false)
      return
    }

    subscriberApi.getSessionInfo(sessionId)
      .then((info) => {
        setSessionInfo(info)
        if (info.already_set_up) {
          setSaved(true)
        }
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Failed to verify donation')
      })
      .finally(() => setLoading(false))
  }, [sessionId])

  async function handleSave(e: FormEvent) {
    e.preventDefault()
    if (!sessionId) return
    setSaving(true)
    setSaveError(null)
    try {
      await subscriberApi.setupProfile({
        session_id: sessionId,
        display_name: displayName.trim().slice(0, 50),
        note: note.trim().slice(0, 280),
        note_is_public: noteIsPublic,
      })
      setSaved(true)
    } catch {
      setSaveError('Could not save your shoutout details, but your donation went through. You can try again later.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16 text-center">
        <p className="text-content-muted">Verifying donation...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16 text-center">
        <div className="mb-6 text-5xl">&#x2764;&#xFE0F;</div>
        <h1 className="font-display text-3xl font-bold text-content mb-3">
          Thank you!
        </h1>
        <p className="text-content-muted mb-8">{error}</p>
        <Link
          to="/recipes/"
          className="inline-flex rounded-xl bg-cta px-6 py-3 text-sm font-semibold text-cta-content shadow-sm hover:bg-cta-hover transition-colors"
        >
          Browse recipes
        </Link>
      </div>
    )
  }

  const isSubscription = sessionInfo?.payment_type === 'subscription'

  return (
    <div className="mx-auto max-w-lg px-4 py-16 text-center">
      <div className="mb-6 text-5xl">&#x2764;&#xFE0F;</div>
      <h1 className="font-display text-3xl font-bold text-content mb-3">
        Thank you for your donation!
      </h1>
      <p className="text-content-muted mb-2">
        Your voluntary donation means the world and helps keep MadeForSeconds free for everyone.
      </p>
      {sessionInfo && (
        <p className="text-sm text-content-muted mb-8">
          {isSubscription
            ? `${sessionInfo.email} — $${(sessionInfo.amount_cents / 100).toFixed(0)}/month donation`
            : `${sessionInfo.email} — $${(sessionInfo.amount_cents / 100).toFixed(0)} donation`}
        </p>
      )}

      {!saved && !skipped ? (
        <div className="rounded-2xl border border-card-border bg-card p-6 mb-8 text-left">
          <h2 className="font-display text-lg font-bold text-content mb-2">
            Want a shoutout?
          </h2>
          <p className="text-sm text-content-muted mb-4">
            Add a display name to appear on the <Link to="/about/#supporters" className="underline hover:text-content">supporters wall</Link>. You can also leave a note — it'll appear once reviewed. Totally optional!
          </p>
          <form onSubmit={handleSave} className="flex flex-col gap-3">
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Your name or nickname"
              maxLength={50}
              autoFocus
              className="rounded-lg border border-card-border px-3 py-2.5 text-sm outline-none focus:border-cta focus:ring-2 focus:ring-cta/40"
            />
            <textarea
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Leave a note (optional)"
              maxLength={280}
              rows={3}
              className="rounded-lg border border-card-border px-3 py-2.5 text-sm outline-none focus:border-cta focus:ring-2 focus:ring-cta/40 resize-none"
            />
            {note.trim() && (
              <label className="flex items-center gap-2 text-sm text-content-muted">
                <input
                  type="checkbox"
                  checked={noteIsPublic}
                  onChange={(e) => setNoteIsPublic(e.target.checked)}
                  className="rounded border-card-border text-accent focus:ring-cta"
                />
                Show my note publicly
              </label>
            )}
            <div className="flex gap-3">
              <button
                type="submit"
                disabled={saving || (!displayName.trim() && !note.trim())}
                className="flex-1 rounded-lg bg-cta px-4 py-2.5 text-sm font-semibold text-cta-content hover:bg-cta-hover transition-colors disabled:opacity-50"
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
              <button
                type="button"
                onClick={() => setSkipped(true)}
                className="rounded-lg px-4 py-2.5 text-sm font-medium text-content-muted hover:text-content-body transition-colors"
              >
                Skip
              </button>
            </div>
            {saveError && (
              <p className="mt-2 text-sm text-danger">{saveError}</p>
            )}
          </form>
        </div>
      ) : saved ? (
        <div className="rounded-2xl border border-success-border bg-success-surface p-6 mb-8">
          <p className="text-sm text-success">
            {displayName.trim()
              ? `You'll appear as "${displayName.trim()}" on the supporters wall. Thanks!`
              : 'All set! Thank you for your donation.'}
          </p>
          {note.trim() && (
            <p className="mt-1 text-xs text-success">Your note will appear once reviewed.</p>
          )}
        </div>
      ) : null}

      <Link
        to="/recipes/"
        className="inline-flex rounded-xl bg-cta px-6 py-3 text-sm font-semibold text-cta-content shadow-sm hover:bg-cta-hover transition-colors"
      >
        Browse recipes
      </Link>
    </div>
  )
}
