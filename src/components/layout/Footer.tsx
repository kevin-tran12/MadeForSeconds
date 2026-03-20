import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { subscriberApi } from '../../lib/api'

export function Footer() {
  const [topSupporters, setTopSupporters] = useState<string[]>([])

  useEffect(() => {
    subscriberApi.listSupporters()
      .then((list) => setTopSupporters(list.slice(0, 5).map((s) => s.display_name)))
      .catch(() => {})
  }, [])

  return (
    <footer className="mt-auto border-t border-surface-darker bg-surface-dark py-8">
      <div className="mx-auto max-w-6xl px-4">

        {topSupporters.length > 0 && (
          <div className="mb-6 text-center">
            <p className="mb-1.5 text-xs font-bold uppercase tracking-widest text-gray-400">
              Supported by
            </p>
            <p className="text-sm text-gray-600">{topSupporters.join(' · ')}</p>
            <Link to="/about#supporters" className="mt-0.5 inline-block text-xs text-gray-400 hover:text-gray-600 transition-colors">
              See all →
            </Link>
          </div>
        )}

        {/* Copyright — truly centered */}
        <p className="mb-5 text-center text-xs text-gray-400">
          &copy; {new Date().getFullYear()} MadeForSeconds · Recipes worth making again.
        </p>

        <div className="flex flex-col items-center justify-between gap-4 md:flex-row">
          {/* Socials */}
          <a
            href="https://linktr.ee/madeforseconds"
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-medium text-gray-700 shadow-sm transition-all hover:bg-gray-50 hover:shadow"
          >
            <svg className="h-4 w-4 text-primary-600" fill="currentColor" viewBox="0 0 24 24">
              <path d="M13.511 5.833L17.5 1.2h-3.132l-2.47 2.871L9.421 1.2H6.289l3.989 4.633L6.289 10.43h3.132l2.477-2.871 2.477 2.871h3.132l-3.998-4.597zM12 10.43V22.8h3V10.43h-3z" />
            </svg>
            Socials
          </a>

          {/* Actions */}
          <div className="flex items-center gap-2">
            <Link
              to="/support"
              className="rounded-md bg-amber-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-600 transition-colors"
            >
              Donate
            </Link>
            <Link
              to="/support/cancel"
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:border-gray-400 hover:text-gray-900 transition-colors"
            >
              Cancel recurring donation
            </Link>
          </div>
        </div>

      </div>
    </footer>
  )
}
