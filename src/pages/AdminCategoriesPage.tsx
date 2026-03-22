import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { adminApi } from '../lib/api'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'

export function AdminCategoriesPage() {
  const [categories, setCategories] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [input, setInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    adminApi
      .getCategories()
      .then(setCategories)
      .catch(() => setError('Failed to load categories'))
      .finally(() => setLoading(false))
  }, [])

  function addCategory() {
    const trimmed = input.trim().toLowerCase()
    if (!trimmed || categories.includes(trimmed)) return
    setCategories([...categories, trimmed].sort())
    setInput('')
  }

  function removeCategory(cat: string) {
    setCategories(categories.filter((c) => c !== cat))
  }

  async function save() {
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const updated = await adminApi.updateCategories(categories)
      setCategories(updated)
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch {
      setError('Failed to save categories')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-10">
      <div className="mb-6 flex items-center gap-3">
        <Link to="/admin" className="text-sm text-gray-500 hover:text-gray-700">← Dashboard</Link>
        <span className="text-gray-300">/</span>
        <h1 className="font-display text-2xl font-bold text-gray-900">Categories</h1>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="rounded-xl border border-surface-darker bg-white p-6 space-y-6">
        <p className="text-sm text-gray-500">
          This list controls which categories can be assigned to recipes. Changes take effect immediately after saving.
        </p>

        {/* Add */}
        <div className="flex gap-2">
          <Input
            id="cat-input"
            label=""
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCategory() } }}
            placeholder="New category name"
          />
          <div className="mt-0 flex items-end">
            <Button type="button" variant="secondary" size="sm" onClick={addCategory}>Add</Button>
          </div>
        </div>

        {/* List */}
        {loading ? (
          <p className="text-sm text-gray-400">Loading…</p>
        ) : categories.length === 0 ? (
          <p className="text-sm text-gray-400">No categories yet. Add one above.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {categories.map((cat) => (
              <span
                key={cat}
                className="inline-flex items-center gap-1.5 rounded-full bg-primary-50 border border-primary-200 px-3 py-1 text-sm font-medium text-primary-800"
              >
                {cat}
                <button
                  type="button"
                  onClick={() => removeCategory(cat)}
                  className="text-primary-400 hover:text-primary-700 leading-none"
                  aria-label={`Remove ${cat}`}
                >
                  ×
                </button>
              </span>
            ))}
          </div>
        )}

        {/* Save */}
        <div className="flex items-center gap-3 pt-2 border-t border-gray-100">
          <Button onClick={save} loading={saving}>Save changes</Button>
          {saved && <span className="text-sm text-green-600 font-medium">Saved!</span>}
        </div>
      </div>
    </div>
  )
}
