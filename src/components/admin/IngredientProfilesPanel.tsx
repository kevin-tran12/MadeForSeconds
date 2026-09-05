import { useCallback, useEffect, useState } from 'react'
import {
  adminIngredientApi,
  type IngredientCoverageRow,
  type IngredientProfile,
  type IngredientProfileInput,
} from '../../lib/api'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { EmptyState } from '../ui/EmptyState'
import { Button } from '../ui/Button'

type Filter = 'missing' | 'covered' | 'all'

interface ProseField {
  key: keyof IngredientProfileInput
  label: string
  max: number
  rows?: number
}

// Same seven fields and caps as backend/app/models.py's IngredientProfileIn —
// mirrored here only for the live character counters, not re-validated
// client-side; the backend is the source of truth.
const PROSE_FIELDS: ProseField[] = [
  { key: 'what_it_is', label: 'What it is', max: 300, rows: 2 },
  { key: 'role', label: 'Role (fat / acid / umami / aromatic / texture)', max: 200 },
  { key: 'substitutions', label: 'Substitutions — what works, what doesn’t, what changes', max: 400, rows: 2 },
  { key: 'buying', label: 'Buying', max: 250 },
  { key: 'storage', label: 'Storage', max: 200 },
  { key: 'mistakes', label: 'Common mistakes', max: 250 },
  { key: 'allergens', label: 'Allergens', max: 100 },
]

const EMPTY_FORM: IngredientProfileInput = {
  name: '', aliases: [], what_it_is: '', role: '', substitutions: '',
  buying: '', storage: '', mistakes: '', allergens: '',
}

function profileToForm(profile: IngredientProfile): IngredientProfileInput {
  return {
    name: profile.name,
    aliases: profile.aliases,
    what_it_is: profile.what_it_is,
    role: profile.role,
    substitutions: profile.substitutions,
    buying: profile.buying,
    storage: profile.storage,
    mistakes: profile.mistakes,
    allergens: profile.allergens,
  }
}

/** The same shape generate_slug() produces server-side, for a brand-new
 * profile's target slug before it exists — `key` here is already
 * canon()-normalised (lowercase, alnum + single spaces only). */
function slugFromKey(key: string): string {
  return key.trim().replace(/\s+/g, '-')
}

export function IngredientProfilesPanel() {
  const [filter, setFilter] = useState<Filter>('missing')
  const [rows, setRows] = useState<IngredientCoverageRow[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [openSlug, setOpenSlug] = useState<string | null>(null)
  const [openIsNew, setOpenIsNew] = useState(false)
  const [form, setForm] = useState<IngredientProfileInput>(EMPTY_FORM)
  const [aliasesText, setAliasesText] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(() => {
    setError(null)
    adminIngredientApi
      .coverage()
      .then(setRows)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load ingredient coverage'))
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function openRow(row: IngredientCoverageRow) {
    setFormError(null)
    if (row.profile_slug) {
      setOpenSlug(row.profile_slug)
      setOpenIsNew(false)
      try {
        const profile = await adminIngredientApi.get(row.profile_slug)
        setForm(profileToForm(profile))
        setAliasesText(profile.aliases.join(', '))
      } catch (err) {
        setFormError(err instanceof Error ? err.message : 'Failed to load profile')
      }
    } else {
      setOpenSlug(slugFromKey(row.key))
      setOpenIsNew(true)
      setForm({ ...EMPTY_FORM, name: row.display })
      setAliasesText('')
    }
  }

  function closeForm() {
    setOpenSlug(null)
    setFormError(null)
  }

  async function handleSave() {
    if (!openSlug) return
    setSaving(true)
    setFormError(null)
    try {
      const payload: IngredientProfileInput = {
        ...form,
        aliases: aliasesText.split(',').map((a) => a.trim()).filter(Boolean),
      }
      await adminIngredientApi.upsert(openSlug, payload)
      closeForm()
      load()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to save the profile')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    if (!openSlug) return
    setSaving(true)
    setFormError(null)
    try {
      await adminIngredientApi.delete(openSlug)
      closeForm()
      load()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : 'Failed to delete the profile')
    } finally {
      setSaving(false)
    }
  }

  if (error) {
    return <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
  }
  if (rows === null) return <LoadingSpinner className="py-12" />

  const visible = rows.filter((row) => {
    if (filter === 'missing') return !row.covered
    if (filter === 'covered') return row.covered
    return true
  })

  return (
    <div>
      <div className="mb-4 flex items-center gap-1 rounded-xl bg-gray-100 p-1 w-fit">
        {(['missing', 'covered', 'all'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 text-sm font-semibold rounded-lg capitalize transition-colors ${
              filter === f ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {visible.length === 0 ? (
        <EmptyState
          title={filter === 'missing' ? 'Every ingredient is covered' : 'No ingredients here'}
          message={
            filter === 'missing'
              ? 'Every ingredient across the published catalogue has an owner-authored profile.'
              : undefined
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-surface-darker bg-white">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 text-left text-xs uppercase tracking-wide text-gray-500">
              <tr>
                <th className="px-4 py-2">Ingredient</th>
                <th className="px-4 py-2">Used in</th>
                <th className="px-4 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr
                  key={row.key}
                  className="cursor-pointer border-t border-gray-100 hover:bg-gray-50"
                  onClick={() => openRow(row)}
                >
                  <td className="px-4 py-2 text-gray-900">{row.display}</td>
                  <td className="px-4 py-2 text-gray-500">
                    {row.recipe_count} recipe{row.recipe_count === 1 ? '' : 's'}
                  </td>
                  <td className="px-4 py-2">
                    {row.covered ? (
                      <span className="text-green-600">
                        Covered{row.via === 'fallback' ? ' (fallback match)' : ''}
                      </span>
                    ) : (
                      <span className="text-amber-600">Missing</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openSlug && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={closeForm}>
          <div
            className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-4 text-lg font-semibold text-gray-900">
              {openIsNew ? 'New ingredient profile' : `Edit ${form.name}`}
            </h3>

            {formError && (
              <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
                {formError}
              </div>
            )}

            <label className="mb-3 block text-sm">
              <span className="mb-1 block font-medium text-gray-700">Name</span>
              <input
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </label>

            <label className="mb-3 block text-sm">
              <span className="mb-1 block font-medium text-gray-700">
                Aliases (comma-separated — every form recipes use, e.g. "garlic cloves, green onions")
              </span>
              <input
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                value={aliasesText}
                onChange={(e) => setAliasesText(e.target.value)}
              />
            </label>

            {PROSE_FIELDS.map(({ key, label, max, rows: fieldRows }) => {
              const value = form[key] as string
              return (
                <label key={key} className="mb-3 block text-sm">
                  <span className="mb-1 flex items-center justify-between font-medium text-gray-700">
                    {label}
                    <span className={value.length > max ? 'text-red-600' : 'text-gray-400'}>
                      {value.length}/{max}
                    </span>
                  </span>
                  <textarea
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                    rows={fieldRows ?? 1}
                    value={value}
                    onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                  />
                </label>
              )
            })}

            <div className="mt-4 flex items-center justify-between">
              <div>
                {!openIsNew && (
                  <Button variant="danger" onClick={handleDelete} disabled={saving}>
                    Delete
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                <Button variant="secondary" onClick={closeForm} disabled={saving}>
                  Cancel
                </Button>
                <Button onClick={handleSave} loading={saving} disabled={!form.name.trim() || !form.what_it_is.trim()}>
                  Save
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
