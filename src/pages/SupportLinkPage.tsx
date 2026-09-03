import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { subscriberApi } from '../lib/api'
import { useAuth } from '../hooks/useAuth'
import { GoogleSignInButton } from '../components/auth/GoogleSignInButton'

/**
 * Link a past donation to the reader's Google account.
 *
 * Donations are recorded under the email Stripe saw, which is often not the
 * reader's Google email. Phase 1 asks for that donation email and sends a
 * signed link (same pattern as cancellation); phase 2, reached from the
 * email while signed in, attaches the reader's uid to the donation records.
 */
export function SupportLinkPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')
  const { user, loginGoogle } = useAuth()

  // Phase 1: request a link
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Phase 2: confirm with the token (needs a signed-in reader)
  const [signingIn, setSigningIn] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [confirmed, setConfirmed] = useState<{ message: string; supporter: boolean } | null>(null)
  const [confirmError, setConfirmError] = useState<string | null>(null)

  useEffect(() => {
    if (!token || !user || confirmed || confirming) return
    setConfirming(true)
    subscriberApi.linkConfirm(token)
      .then((res) => setConfirmed(res))
      .catch((err) => setConfirmError(err instanceof Error ? err.message : 'Could not link your donation'))
      .finally(() => setConfirming(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, user])

  async function handleSignIn() {
    setSigningIn(true)
    setConfirmError(null)
    try {
      await loginGoogle()
    } catch (err) {
      setConfirmError(err instanceof Error ? err.message : 'Sign-in failed')
    } finally {
      setSigningIn(false)
    }
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await subscriberApi.linkRequest(email.trim())
      setSubmitted(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setSubmitting(false)
    }
  }

  if (token) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16 text-center">
        {confirmed ? (
          <>
            <div className="mb-6 text-5xl">&#x2764;&#xFE0F;</div>
            <h1 className="font-display text-2xl font-bold text-content mb-3">Donation linked</h1>
            <p className="text-content-muted mb-8">{confirmed.message}</p>
            <Link
              to="/recipes/"
              className="inline-flex rounded-xl bg-cta px-6 py-3 text-sm font-semibold text-cta-content shadow-sm hover:bg-cta-hover transition-colors"
            >
              Browse recipes
            </Link>
          </>
        ) : confirmError ? (
          <>
            <div className="mb-6 text-5xl">&#x26A0;&#xFE0F;</div>
            <h1 className="font-display text-2xl font-bold text-content mb-3">Linking failed</h1>
            <p className="text-content-muted mb-4">{confirmError}</p>
            <Link to="/support/link/" className="text-sm font-medium text-accent hover:text-accent-hover transition-colors">
              Request a new link
            </Link>
          </>
        ) : !user ? (
          <div className="mx-auto max-w-sm rounded-2xl border border-card-border bg-card p-6">
            <h1 className="font-display text-2xl font-bold text-content mb-3">One more step</h1>
            <p className="text-sm text-content-muted mb-5">
              Sign in with the Google account you use on MadeForSeconds. Your donation will be
              attached to it.
            </p>
            <GoogleSignInButton onClick={handleSignIn} loading={signingIn} label="Sign in with Google to finish" />
          </div>
        ) : (
          <p className="text-content-muted">Linking your donation...</p>
        )}
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-16">
      <div className="text-center mb-10">
        <h1 className="font-display text-2xl font-bold text-content mb-3">Link a past donation</h1>
        <p className="text-content-muted">
          Donated with a different email than your Google account? Enter the email you used at
          checkout and we'll send a link that attaches that donation to your account.
        </p>
      </div>

      {submitted ? (
        <div className="rounded-2xl border border-success-border bg-success-surface p-6 text-center">
          <p className="text-sm text-success mb-2 font-semibold">Check your email</p>
          <p className="text-sm text-success">
            If a donation exists for this email, we've sent a link. It expires in 1 hour.
          </p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="rounded-2xl border border-card-border bg-card p-6">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="email used at checkout"
            aria-label="Donation email"
            required
            autoFocus
            className="mb-4 w-full rounded-lg border border-card-border px-3 py-2.5 text-sm outline-none focus:border-cta focus:ring-2 focus:ring-cta/40"
          />

          {error && (
            <div className="mb-4 rounded-lg bg-danger-surface border border-danger-border px-3 py-2 text-sm text-danger">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !email.trim()}
            className="w-full rounded-xl bg-neutral py-3 text-sm font-bold text-neutral-content hover:bg-neutral-hover transition-colors disabled:opacity-50"
          >
            {submitting ? 'Sending...' : 'Send link'}
          </button>

          <p className="mt-4 text-center text-xs text-content-muted">
            {user
              ? `You're signed in as ${user.email}; the donation will attach to this account.`
              : "You'll be asked to sign in with Google when you open the link."}
          </p>
        </form>
      )}
    </div>
  )
}
