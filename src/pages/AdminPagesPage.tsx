import { Link } from 'react-router-dom'

const PAGES = [
  { id: 'home', label: 'Home', description: 'Hero title and subtitle shown on the landing page.' },
  { id: 'about', label: 'About', description: 'Heading, body paragraphs, callout box, and sidebar text.' },
]

export function AdminPagesPage() {
  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex items-center gap-3">
        <Link to="/admin/" className="text-sm text-gray-500 hover:text-gray-700">← Dashboard</Link>
        <span className="text-gray-300">/</span>
        <h1 className="font-display text-2xl font-bold text-gray-900">Pages</h1>
      </div>

      <div className="space-y-3">
        {PAGES.map((page) => (
          <Link
            key={page.id}
            to={`/admin/pages/${page.id}/`}
            className="flex items-center justify-between rounded-xl border border-surface-darker bg-white px-5 py-4 transition-colors hover:border-primary-200 hover:bg-primary-50/30"
          >
            <div>
              <p className="font-semibold text-gray-900">{page.label}</p>
              <p className="text-sm text-gray-500 mt-0.5">{page.description}</p>
            </div>
            <svg className="h-5 w-5 text-gray-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </Link>
        ))}
      </div>
    </div>
  )
}
