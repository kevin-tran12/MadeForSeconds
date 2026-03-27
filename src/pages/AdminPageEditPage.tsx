import { useState, useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import { adminApi } from '../lib/api'
import { Button } from '../components/ui/Button'

// Schema: which fields each page has, display labels, and whether they're multi-line
const PAGE_SCHEMAS: Record<string, { key: string; label: string; hint?: string; multiline?: boolean }[]> = {
  home: [
    { key: 'hero_title', label: 'Hero Title', hint: 'Large heading shown in the hero section.' },
    { key: 'hero_subtitle', label: 'Hero Subtitle', hint: 'Tagline below the title.' },
  ],
  about: [
    { key: 'heading', label: 'Page Heading', hint: 'Main h1 at the top of the about page.' },
    {
      key: 'body',
      label: 'Body',
      hint: 'Separate paragraphs with a blank line (double newline).',
      multiline: true,
    },
    { key: 'callout_title', label: 'Callout Box Title' },
    { key: 'callout_body', label: 'Callout Box Text', multiline: true },
    { key: 'follow_heading', label: 'Sidebar "Follow" Heading' },
    { key: 'thank_you_message', label: 'Supporters Thank-You Message', multiline: true },
  ],
}

const PAGE_LABELS: Record<string, string> = { home: 'Home', about: 'About' }

export function AdminPageEditPage() {
  const { pageId = '' } = useParams<{ pageId: string }>()
  const schema = PAGE_SCHEMAS[pageId] ?? []
  const pageLabel = PAGE_LABELS[pageId] ?? pageId

  const [fields, setFields] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    adminApi
      .getPageContent(pageId)
      .then(setFields)
      .catch(() => setError('Failed to load page content'))
      .finally(() => setLoading(false))
  }, [pageId])

  function setField(key: string, value: string) {
    setFields((prev) => ({ ...prev, [key]: value }))
  }

  async function save() {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const updated = await adminApi.updatePageContent(pageId, fields)
      setFields(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch {
      setError('Failed to save page content')
    } finally {
      setSaving(false)
    }
  }

  if (!schema.length) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-10">
        <p className="text-sm text-gray-500">Unknown page: <code>{pageId}</code></p>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex items-center gap-3">
        <Link to="/admin/" className="text-sm text-gray-500 hover:text-gray-700">← Dashboard</Link>
        <span className="text-gray-300">/</span>
        <Link to="/admin/pages/" className="text-sm text-gray-500 hover:text-gray-700">Pages</Link>
        <span className="text-gray-300">/</span>
        <h1 className="font-display text-2xl font-bold text-gray-900">{pageLabel}</h1>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (
        <div className="rounded-xl border border-surface-darker bg-white p-6 space-y-6">
          {schema.map(({ key, label, hint, multiline }) => (
            <div key={key} className="flex flex-col gap-1">
              <label htmlFor={key} className="text-sm font-medium text-gray-700">
                {label}
              </label>
              {hint && <p className="text-xs text-gray-400">{hint}</p>}
              {multiline ? (
                <textarea
                  id={key}
                  rows={6}
                  value={fields[key] ?? ''}
                  onChange={(e) => setField(key, e.target.value)}
                  className="resize-y rounded-lg border border-gray-300 px-3 py-2 font-mono text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                />
              ) : (
                <input
                  id={key}
                  type="text"
                  value={fields[key] ?? ''}
                  onChange={(e) => setField(key, e.target.value)}
                  className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
                />
              )}
            </div>
          ))}

          <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
            <Button onClick={save} loading={saving}>Save changes</Button>
            {saved && <span className="text-sm text-green-600 font-medium">Saved!</span>}
          </div>
        </div>
      )}
    </div>
  )
}
