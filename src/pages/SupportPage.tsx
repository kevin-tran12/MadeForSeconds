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
        <h1 className="font-display text-3xl font-bold text-gray-900 mb-3">
          Donate to MadeForSeconds
        </h1>
        <p className="text-gray-600">
          Everything on MadeForSeconds is free. If you love what we cook, your
          voluntary donation helps keep the recipes coming.
        </p>
      </div>

      <div className="rounded-2xl border border-gray-200 bg-white p-6">
        {/* One-time / Monthly toggle */}
        <div className="mb-5 flex rounded-xl bg-gray-100 p-1">
          <button
            onClick={() => setOneTime(false)}
            className={`flex-1 rounded-lg py-2 text-sm font-semibold transition-all ${
              !oneTime
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            Monthly
          </button>
          <button
            onClick={() => setOneTime(true)}
            className={`flex-1 rounded-lg py-2 text-sm font-semibold transition-all ${
              oneTime
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
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
                  ? 'bg-amber-500 text-white shadow-sm'
                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
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
              isCustom ? 'text-amber-600' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            Custom amount
          </button>
          {isCustom && (
            <div className="flex items-center gap-2">
              <span className="text-lg font-bold text-gray-400">$</span>
              <input
                type="number"
                min="1"
                max="500"
                value={custom}
                onChange={(e) => setCustom(e.target.value)}
                placeholder="Enter amount"
                autoFocus
                className="flex-1 rounded-lg border border-gray-300 px-3 py-2.5 text-sm outline-none focus:border-amber-500 focus:ring-2 focus:ring-amber-100"
              />
              {!oneTime && <span className="text-sm text-gray-400">/month</span>}
            </div>
          )}
        </div>

        {error && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Checkout button */}
        <button
          onClick={handleCheckout}
          disabled={!valid || loading}
          className="w-full rounded-xl bg-amber-500 py-3 text-sm font-bold text-white shadow-sm hover:bg-amber-600 transition-colors disabled:opacity-50"
        >
          {loading
            ? 'Redirecting...'
            : oneTime
              ? `Donate — $${amount}`
              : `Donate — $${amount}/month`}
        </button>

        <p className="mt-4 text-center text-xs text-gray-500">
          After donating, you can optionally set a display name and note to be included in the supporters shoutout on the <Link to="/about#supporters" className="underline hover:text-gray-700">About page</Link>.
        </p>
        <p className="mt-2 text-center text-xs text-gray-400">
          {oneTime ? (
            'Powered by Stripe'
          ) : (
            <>
              <Link to="/support/cancel" className="hover:text-gray-600 underline">Cancel recurring donation</Link>
              {' · Powered by Stripe'}
            </>
          )}
        </p>
      </div>

      {/* Disclaimers */}
      <div className="mt-6 rounded-xl border border-gray-100 bg-gray-50 p-4 text-xs text-gray-400 space-y-1.5">
        <p><span className="font-semibold text-gray-500">Donations</span> are processed securely by Stripe. MadeForSeconds does not store your card details.</p>
        <p><span className="font-semibold text-gray-500">Recurring donations</span> renew automatically each month until canceled. Cancellations take effect at the end of the current billing period.</p>
        <p><span className="font-semibold text-gray-500">One-time donations</span> are final and non-refundable.</p>
        <p><span className="font-semibold text-gray-500">Shoutouts</span> are voluntary, revocable, and subject to review. We reserve the right to remove any display name or note at our discretion.</p>
        <p><span className="font-semibold text-gray-500">No goods or services.</span> Your donation is a voluntary gift. It does not entitle you to any product, service, or exclusive content.</p>
      </div>

      {/* Subscription confirmation modal */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="w-full max-w-sm rounded-2xl bg-white p-6 shadow-xl">
            <h2 className="font-display text-lg font-bold text-gray-900 mb-2">
              Confirm recurring donation
            </h2>
            <p className="text-sm text-gray-600 mb-4">
              You'll be charged <span className="font-semibold">${amount}/month</span> until
              you cancel. You can cancel anytime via email.
            </p>
            <div className="flex gap-3">
              <button
                onClick={doCheckout}
                disabled={loading}
                className="flex-1 rounded-lg bg-amber-500 py-2.5 text-sm font-bold text-white hover:bg-amber-600 transition-colors disabled:opacity-50"
              >
                {loading ? 'Redirecting...' : 'Continue'}
              </button>
              <button
                onClick={() => setShowConfirm(false)}
                className="rounded-lg px-4 py-2.5 text-sm font-medium text-gray-500 hover:text-gray-700 transition-colors"
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
