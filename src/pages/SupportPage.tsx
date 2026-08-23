import { useState } from 'react'
import { Link } from 'react-router-dom'
import { subscriberApi } from '../lib/api'

const PRESETS = [1, 5, 10, 25]

export function SupportPage() {
  const [selected, setSelected] = useState(1)
  const [custom, setCustom] = useState('')
  const [isCustom, setIsCustom] = useState(false)
  const [oneTime, setOneTime] = useState(true)
  const [showConfirm, setShowConfirm] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const amount = isCustom ? parseInt(custom) || 0 : selected
  const valid = amount >= 1 && amount <= 500

  async function doCheckout() {
    if (!valid) return
    setLoading(true)
    setError(null)
    try {
      const { checkout_url } = await subscriberApi.createCheckout(
        amount * 100,
        `${window.location.origin}/support/success?session_id={CHECKOUT_SESSION_ID}`,
        window.location.href,
        oneTime
      )
      window.location.href = checkout_url
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
      setShowConfirm(false)
    }
  }

  function handleCheckout() {
    if (!valid) return
    if (!oneTime) {
      setShowConfirm(true)
    } else {
      doCheckout()
    }
  }

  return (
    <div className="mx-auto max-w-lg px-4 py-16">
      <div className="text-center mb-10">
        <h1 className="font-display text-3xl font-bold text-content mb-3">
          Donate to MadeForSeconds
        </h1>
        <p className="text-content-muted">
          Everything on MadeForSeconds is free. If you love what we cook, your
          voluntary donation helps keep the recipes coming.
        </p>
      </div>

      <div className="rounded-2xl border border-card-border bg-card p-6">
        {/* One-time / Monthly toggle */}
        <div className="mb-5 flex rounded-xl bg-card-muted p-1">
          <button
            onClick={() => setOneTime(false)}
            className={`flex-1 rounded-lg py-2 text-sm font-semibold transition-all ${
              !oneTime
                ? 'bg-card text-content shadow-sm'
                : 'text-content-muted hover:text-content-body'
            }`}
          >
            Monthly
          </button>
          <button
            onClick={() => setOneTime(true)}
            className={`flex-1 rounded-lg py-2 text-sm font-semibold transition-all ${
              oneTime
                ? 'bg-card text-content shadow-sm'
                : 'text-content-muted hover:text-content-body'
            }`}
          >
            One time
          </button>
        </div>

        {/* Preset amounts */}
        <div className="grid grid-cols-4 gap-2 mb-4">
          {PRESETS.map((amt) => (
            <button
              key={amt}
              onClick={() => { setSelected(amt); setIsCustom(false) }}
              className={`rounded-xl py-3 text-sm font-bold transition-all ${
                !isCustom && selected === amt
                  ? 'bg-cta text-cta-content shadow-sm'
                  : 'bg-card-muted text-content-body hover:bg-card-border'
              }`}
            >
              ${amt}
            </button>
          ))}
        </div>

        {/* Custom amount */}
        <div className="mb-6">
          <button
            onClick={() => setIsCustom(true)}
            className={`mb-2 text-sm font-medium transition-colors ${
              isCustom ? 'text-accent' : 'text-content-muted hover:text-content-body'
            }`}
          >
            Custom amount
          </button>
          {isCustom && (
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-content-muted">$</span>
              <input
                type="number"
                min="1"
                max="500"
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                placeholder="Enter amount"
                autoFocus
                className="flex-1 rounded-lg border border-card-border px-3 py-2.5 text-sm outline-none focus:border-cta focus:ring-2 focus:ring-cta/40"
              />
              {!oneTime && <span className="text-sm text-content-muted">/month</span>}
            </div>
          )}
        </div>

        {error && (
          <div className="mb-4 rounded-lg bg-danger-surface border border-danger-border px-3 py-2 text-sm text-danger">
            {error}
          </div>
        )}

        {/* Checkout button */}
        <button
          onClick={handleCheckout}
          disabled={!valid || loading}
          className="w-full rounded-xl bg-cta py-3 text-sm font-bold text-cta-content shadow-sm hover:bg-cta-hover transition-colors disabled:opacity-50"
        >
          {loading
            ? 'Redirecting...'
            : oneTime
              ? `Donate — $${amount}`
              : `Donate — $${amount}/month`}
        </button>

        <p className="mt-4 text-center text-xs text-content-muted">
          After donating, you can optionally set a display name and note to be included in the supporters shoutout on the <Link to="/about/#supporters" className="underline hover:text-content-body">About page</Link>.
        </p>
        <p className="mt-2 text-center text-xs text-content-muted">
          {oneTime ? (
            'Powered by Stripe'
          ) : (
            <>
              <Link to="/support/cancel/" className="hover:text-content-muted underline">Cancel recurring donation</Link>
              {' · Powered by Stripe'}
            </>
          )}
        </p>
      </div>

      {/* Disclaimers */}
      <div className="mt-6 rounded-xl border border-card-border bg-card-muted p-4 text-xs text-content-muted space-y-1.5">
        <p><span className="font-semibold text-content-muted">Donations</span> are processed securely by Stripe. MadeForSeconds does not store your card details.</p>
        <p><span className="font-semibold text-content-muted">Recurring donations</span> renew automatically each month until canceled. Cancellations take effect at the end of the current billing period.</p>
        <p><span className="font-semibold text-content-muted">One-time donations</span> are final and non-refundable.</p>
        <p><span className="font-semibold text-content-muted">Shoutouts</span> are voluntary, revocable, and subject to review. We reserve the right to remove any display name or note at our discretion.</p>
        <p><span className="font-semibold text-content-muted">No goods or services.</span> Your donation is a voluntary gift. It does not entitle you to any product, service, or exclusive content.</p>
      </div>

      {/* Subscription confirmation modal */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-modal-scrim px-4">
          <div className="w-full max-w-sm rounded-2xl bg-card p-6 shadow-xl">
            <h2 className="font-display text-lg font-bold text-content mb-2">
              Confirm recurring donation
            </h2>
            <p className="text-sm text-content-muted mb-4">
              You'll be charged <span className="font-semibold">${amount}/month</span> until
              you cancel. You can cancel anytime via email.
            </p>
            <div className="flex gap-3">
              <button
                onClick={doCheckout}
                disabled={loading}
                className="flex-1 rounded-lg bg-cta py-2.5 text-sm font-bold text-cta-content hover:bg-cta-hover transition-colors disabled:opacity-50"
              >
                {loading ? 'Redirecting...' : 'Continue'}
              </button>
              <button
                onClick={() => setShowConfirm(false)}
                className="rounded-lg px-4 py-2.5 text-sm font-medium text-content-muted hover:text-content-body transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
