import { useEffect, useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { subscriberApi } from '../lib/api'

export function SupportCancelPage() {
  const [searchParams] = useSearchParams()
  const token = searchParams.get('token')

  // Phase 1: email form
  const [email, setEmail] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Phase 2: token confirmation
  const [confirming, setConfirming] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [confirmMessage, setConfirmMessage] = useState('')
  const [confirmError, setConfirmError] = useState<string | null>(null)

  // If there's a token in the URL, auto-confirm
  useEffect(() => {
    if (!token) return
    setConfirming(true)
    subscriberApi.confirmCancel(token)
      .then((res) => {
        setConfirmed(true)
        setConfirmMessage(res.message)
      })
      .catch((err) => {
        setConfirmError(err instanceof Error ? err.message : 'Failed to cancel donation')
      })
      .finally(() => setConfirming(false))
  }, [token])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    setSubmitting(true)
    setError(null)
    try {
      await subscriberApi.requestCancel(email.trim())
      setSubmitted(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setSubmitting(false)
    }
  }

  // Phase 2: Token-based confirmation
  if (token) {
    return (
      <div className="mx-auto max-w-lg px-4 py-16 text-center">
        {confirming ? (
          <p className="text-gray-500">Canceling your donation...</p>
        ) : confirmed ? (
          <>
            <div className="mb-6 text-5xl">&#x1F44B;</div>
            <h1 className="font-display text-2xl font-bold text-gray-900 mb-3">
              Donation Canceled
            </h1>
            <p className="text-gray-600 mb-8">{confirmMessage}</p>
            <Link
              to="/recipes/"
              className="inline-flex rounded-xl bg-amber-600 px-6 py-3 text-sm font-semibold text-white shadow-sm hover:bg-amber-700 transition-colors"
            >
              Browse recipes
            </Link>
          </>
        ) : (
          <>
            <div className="mb-6 text-5xl">&#x26A0;&#xFE0F;</div>
            <h1 className="font-display text-2xl font-bold text-gray-900 mb-3">
              Cancellation Failed
            </h1>
            <p className="text-gray-600 mb-4">{confirmError}</p>
            <Link
              to="/support/cancel/"
              className="text-sm font-medium text-amber-600 hover:text-amber-700 transition-colors"
            >
              Try again
            </Link>
          </>
        )}
      </div>
    )
  }

  // Phase 1: Email form
  return (
    <div className="mx-auto max-w-lg px-4 py-16">
      <div className="text-center mb-10">
        <h1 className="font-display text-2xl font-bold text-gray-900 mb-3">
          Cancel Recurring Donation
        </h1>
        <p className="text-gray-600">
          Enter the email address you used when donating. We'll send you a
          confirmation link to complete the cancellation.
        </p>
      </div>

      {submitted ? (
        <div className="rounded-2xl border border-green-200 bg-green-50 p-6 text-center">
          <p className="text-sm text-green-700 mb-2 font-semibold">Check your email</p>
          <p className="text-sm text-green-600">
            If an active recurring donation exists for this email, we've sent a confirmation link.
            The link expires in 1 hour.
          </p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="rounded-2xl border border-gray-200 bg-white p-6">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="your@email.com"
            required
            autoFocus
            className="mb-4 w-full rounded-lg border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-100"
          />

          {error && (
            <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !email.trim()}
            className="w-full rounded-xl bg-gray-800 py-3 text-sm font-bold text-white hover:bg-gray-900 transition-colors disabled:opacity-50"
          >
            {submitting ? 'Sending...' : 'Send cancellation link'}
          </button>

          <p className="mt-4 text-center text-xs text-gray-400">
            We'll email you a confirmation link. Your donation stays active until you click it.
          </p>
        </form>
      )}

      <div className="mt-8 rounded-xl bg-gray-50 border border-gray-200 p-4">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Other ways to cancel</p>
        <ul className="text-sm text-gray-600 space-y-1.5 list-disc list-inside">
          <li>Log in to <a href="https://billing.stripe.com" target="_blank" rel="noopener noreferrer" className="text-amber-600 hover:underline">Stripe's billing portal</a> directly using your email</li>
          <li>Contact your bank or card provider to stop the recurring gift</li>
        </ul>
      </div>
    </div>
  )
}
