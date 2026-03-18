import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { adminTotpApi } from '../../lib/api'
import { setTotpToken, getTotpToken } from '../../lib/api-client'

type TotpState = 'loading' | 'setup' | 'verify' | 'verified'

export function TotpGate() {
  // Dev mode: skip TOTP entirely
  if (import.meta.env.DEV) {
    return <Outlet />
  }

  return <TotpGateInner />
}

function TotpGateInner() {
  const [state, setState] = useState<TotpState>('loading')
  const [code, setCode] = useState('')
  const [error, setError] = useState('')
  const [setupData, setSetupData] = useState<{ secret: string; qr_code: string } | null>(null)
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    checkStatus()
  }, [])

  // When the 12h session JWT expires, apiFetch clears the token and fires this
  // event. Drop back to the verify screen instead of letting 403s bubble up.
  useEffect(() => {
    const handler = () => setState('verify')
    window.addEventListener('totp-session-expired', handler)
    return () => window.removeEventListener('totp-session-expired', handler)
  }, [])

  async function checkStatus() {
    // If we already have a valid session token, try using it
    if (getTotpToken()) {
      setState('verified')
      return
    }

    try {
      const { enabled } = await adminTotpApi.getStatus()
      setState(enabled ? 'verify' : 'setup')
    } catch {
      setState('setup')
    }
  }

  async function handleSetup() {
    setError('')
    try {
      const data = await adminTotpApi.setup()
      setSetupData(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Setup failed')
    }
  }

  async function handleConfirmSetup() {
    if (!setupData || code.length !== 6) return
    setSubmitting(true)
    setError('')
    try {
      const { token } = await adminTotpApi.confirmSetup(setupData.secret, code)
      setTotpToken(token)
      setState('verified')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid code')
    } finally {
      setSubmitting(false)
      setCode('')
    }
  }

  async function handleVerify() {
    if (code.length !== 6) return
    setSubmitting(true)
    setError('')
    try {
      const { token } = await adminTotpApi.verify(code)
      setTotpToken(token)
      setState('verified')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Invalid code')
    } finally {
      setSubmitting(false)
      setCode('')
    }
  }

  if (state === 'loading') {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <p className="text-secondary">Checking authentication...</p>
      </div>
    )
  }

  if (state === 'verified') {
    return <Outlet />
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center">
      <div className="w-full max-w-md rounded-lg border border-gray-200 bg-white p-8 shadow-sm">
        {state === 'setup' && !setupData && (
          <>
            <h2 className="mb-2 text-xl font-semibold text-gray-900">Set Up 2FA</h2>
            <p className="mb-6 text-sm text-gray-600">
              The expense ledger requires two-factor authentication. Set up Google Authenticator to continue.
            </p>
            <button
              onClick={handleSetup}
              className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-white hover:bg-brand/90"
            >
              Generate QR Code
            </button>
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          </>
        )}

        {state === 'setup' && setupData && (
          <>
            <h2 className="mb-2 text-xl font-semibold text-gray-900">Scan QR Code</h2>
            <p className="mb-4 text-sm text-gray-600">
              Scan this code with Google Authenticator, then enter the 6-digit code below.
            </p>
            <div className="mb-4 flex justify-center">
              <img src={setupData.qr_code} alt="TOTP QR Code" className="h-48 w-48" />
            </div>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={6}
              placeholder="Enter 6-digit code"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              onKeyDown={(e) => e.key === 'Enter' && handleConfirmSetup()}
              className="mb-3 w-full rounded-lg border border-gray-300 px-4 py-2.5 text-center text-lg tracking-widest focus:border-brand focus:ring-1 focus:ring-brand focus:outline-none"
              autoFocus
            />
            <button
              onClick={handleConfirmSetup}
              disabled={code.length !== 6 || submitting}
              className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-white hover:bg-brand/90 disabled:opacity-50"
            >
              {submitting ? 'Verifying...' : 'Confirm Setup'}
            </button>
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          </>
        )}

        {state === 'verify' && (
          <>
            <h2 className="mb-2 text-xl font-semibold text-gray-900">Enter 2FA Code</h2>
            <p className="mb-6 text-sm text-gray-600">
              Open Google Authenticator and enter the 6-digit code for MadeForSeconds.
            </p>
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              maxLength={6}
              placeholder="Enter 6-digit code"
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              onKeyDown={(e) => e.key === 'Enter' && handleVerify()}
              className="mb-3 w-full rounded-lg border border-gray-300 px-4 py-2.5 text-center text-lg tracking-widest focus:border-brand focus:ring-1 focus:ring-brand focus:outline-none"
              autoFocus
            />
            <button
              onClick={handleVerify}
              disabled={code.length !== 6 || submitting}
              className="w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-medium text-white hover:bg-brand/90 disabled:opacity-50"
            >
              {submitting ? 'Verifying...' : 'Verify'}
            </button>
            {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          </>
        )}
      </div>
    </div>
  )
}
