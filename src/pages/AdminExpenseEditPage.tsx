import { useState, useEffect, useMemo, useRef } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { adminExpenseApi, adminApi } from '../lib/api'
import type { Recipe } from '../lib/types'
import type { ExpenseItem, ExpenseCreate } from '../lib/types-expense'
import { EXPENSE_CATEGORIES, formatCents, recalcProjectAmounts } from '../lib/types-expense'
import type { ExpenseCategory } from '../lib/types-expense'
import { ExpenseItemEditor } from '../components/admin/ExpenseItemEditor'
import { ReceiptItemizer } from '../components/admin/ReceiptItemizer'
import { Button } from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

export function AdminExpenseEditPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isNew = !id
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Form state
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [vendor, setVendor] = useState('')
  const [category, setCategory] = useState<ExpenseCategory>('other')
  const [description, setDescription] = useState('')
  const [recipeId, setRecipeId] = useState<string | null>(null)
  const [purpose, setPurpose] = useState('')
  const [items, setItems] = useState<ExpenseItem[]>([])
  const [rawSubtotal, setRawSubtotal] = useState(0)
  const [rawTax, setRawTax] = useState(0)
  const [rawTotal, setRawTotal] = useState(0)

  // Receipt
  const [receiptUrl, setReceiptUrl] = useState<string | null>(null)
  const [receiptFilename, setReceiptFilename] = useState<string | null>(null)
  const [receiptContentType, setReceiptContentType] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [aiParsed, setAiParsed] = useState(false)

  // Recipes list for linking
  const [recipes, setRecipes] = useState<Recipe[]>([])

  // UI state
  const [loading, setLoading] = useState(!isNew)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Load recipes for dropdown
  useEffect(() => {
    adminApi.listRecipes().then(setRecipes).catch(() => {})
  }, [])

  // Load existing expense
  useEffect(() => {
    if (!id) return
    setLoading(true)
    adminExpenseApi
      .get(id)
      .then((exp) => {
        setDate(exp.date.slice(0, 10))
        setVendor(exp.vendor)
        setCategory(exp.category)
        setDescription(exp.description)
        setRecipeId(exp.recipe_id)
        setPurpose(exp.purpose ?? '')
        setItems(exp.items)
        setRawSubtotal(exp.raw_subtotal)
        setRawTax(exp.raw_tax)
        setRawTotal(exp.raw_total)
        setReceiptUrl(exp.receipt_url)
        setReceiptFilename(exp.receipt_filename)
        setReceiptContentType(exp.receipt_content_type)
        setAiParsed(exp.ai_parsed)
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load'))
      .finally(() => setLoading(false))
  }, [id])

  // Live project amount calculation
  const project = useMemo(
    () => recalcProjectAmounts(items, rawTax, rawSubtotal),
    [items, rawTax, rawSubtotal]
  )

  async function handleReceiptUpload(file: File) {
    setUploading(true)
    setError(null)
    try {
      const result = await adminExpenseApi.uploadReceipt(file)
      setReceiptUrl(result.receipt_url)
      setReceiptFilename(result.receipt_filename)
      setReceiptContentType(result.receipt_content_type)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function handleScanReceipt(file: File) {
    setScanning(true)
    setError(null)
    try {
      const parsed = await adminExpenseApi.parseReceipt(file)
      if (parsed.vendor) setVendor(parsed.vendor)
      if (parsed.date) setDate(parsed.date.slice(0, 10))
      if (parsed.items?.length) setItems(parsed.items)
      if (parsed.raw_subtotal) setRawSubtotal(parsed.raw_subtotal)
      if (parsed.raw_tax) setRawTax(parsed.raw_tax)
      if (parsed.raw_total) setRawTotal(parsed.raw_total)
      setAiParsed(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Receipt scan failed')
    } finally {
      setScanning(false)
    }
  }

  async function handleReceiptFileSelected(file: File) {
    // Upload and scan in parallel
    await Promise.all([handleReceiptUpload(file), handleScanReceipt(file)])
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!vendor.trim()) {
      setError('Vendor is required')
      return
    }

    setSaving(true)
    setError(null)
    try {
      const data: ExpenseCreate = {
        date: new Date(date).toISOString(),
        vendor: vendor.trim(),
        category,
        description: description.trim(),
        recipe_id: recipeId || null,
        purpose: recipeId ? null : purpose.trim() || null,
        items,
        raw_subtotal: rawSubtotal,
        raw_tax: rawTax,
        raw_total: rawTotal,
      }

      let saved
      if (isNew) {
        saved = await adminExpenseApi.create({ ...data, ai_parsed: aiParsed } as never)
      } else {
        saved = await adminExpenseApi.update(id!, data)
      }

      // Attach receipt if uploaded but not yet linked
      if (receiptUrl && saved.receipt_url !== receiptUrl) {
        await adminExpenseApi.update(saved.id, {
          receipt_url: receiptUrl,
          receipt_filename: receiptFilename,
          receipt_content_type: receiptContentType,
        } as never)
      }

      navigate('/admin/expenses')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <LoadingSpinner size="lg" className="py-16" />

  const inputClass =
    'rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100'

  return (
    <div className="mx-auto max-w-4xl px-4 py-10">
      <Link to="/admin/expenses" className="text-sm text-primary-600 hover:text-primary-700 mb-4 inline-block">
        ← Back to Expenses
      </Link>
      <h1 className="mb-6 text-2xl font-bold text-gray-900 font-display">
        {isNew ? 'New Expense' : 'Edit Expense'}
      </h1>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Basic info */}
        <section className="rounded-xl border border-surface-darker bg-white p-6 space-y-4">
          <h2 className="text-lg font-semibold text-gray-900">Details</h2>
          <div className="grid grid-cols-2 gap-4">
            <Input id="date" label="Date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            <Input id="vendor" label="Vendor" value={vendor} onChange={(e) => setVendor(e.target.value)} placeholder="e.g. Costco, AWS, Amazon" />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="category" className="mb-1 block text-sm font-medium text-gray-700">
                Category
              </label>
              <select
                id="category"
                value={category}
                onChange={(e) => setCategory(e.target.value as ExpenseCategory)}
                className={`w-full ${inputClass}`}
              >
                {EXPENSE_CATEGORIES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="recipe" className="mb-1 block text-sm font-medium text-gray-700">
                Linked Recipe (optional)
              </label>
              <select
                id="recipe"
                value={recipeId ?? ''}
                onChange={(e) => setRecipeId(e.target.value || null)}
                className={`w-full ${inputClass}`}
              >
                <option value="">— No recipe —</option>
                {recipes.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.title}
                  </option>
                ))}
              </select>
            </div>
          </div>
          {!recipeId && (
            <Input
              id="purpose"
              label="Purpose"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
              placeholder="e.g. KitchenAid mixer, Cloudflare domain renewal"
            />
          )}
          <div>
            <label htmlFor="description" className="mb-1 block text-sm font-medium text-gray-700">
              Notes
            </label>
            <textarea
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Additional notes..."
              className={`w-full resize-none ${inputClass}`}
            />
          </div>
        </section>

        {/* Receipt upload */}
        <section className="rounded-xl border border-surface-darker bg-white p-6 space-y-4">
          <h2 className="text-lg font-semibold text-gray-900">Receipt</h2>
          {receiptFilename ? (
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 rounded-lg bg-green-50 border border-green-200 px-3 py-2 text-sm text-green-700">
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                {receiptFilename}
              </div>
              <Button
                type="button"
                variant="secondary"
                size="sm"
                onClick={() => {
                  setReceiptUrl(null)
                  setReceiptFilename(null)
                  setReceiptContentType(null)
                }}
              >
                Remove
              </Button>
            </div>
          ) : (
            <div>
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*,application/pdf"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) handleReceiptFileSelected(f)
                }}
              />
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                disabled={uploading}
                className="flex w-full items-center justify-center gap-2 rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 px-6 py-8 text-sm text-gray-500 transition hover:border-primary-400 hover:bg-primary-50 disabled:opacity-50"
              >
                {uploading ? (
                  <>
                    <LoadingSpinner size="sm" />
                    {scanning ? 'Scanning with AI…' : 'Uploading…'}
                  </>
                ) : (
                  <>
                    <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 16v-8m0 0l-3 3m3-3l3 3M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2" />
                    </svg>
                    Click to upload receipt — AI will extract items automatically
                  </>
                )}
              </button>
            </div>
          )}
        </section>

        {/* Line items */}
        <section className="rounded-xl border border-surface-darker bg-white p-6 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">Line Items</h2>
            {aiParsed && (
              <span className="flex items-center gap-1 rounded-full bg-green-50 px-2.5 py-1 text-xs font-medium text-green-700 border border-green-200">
                <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                </svg>
                Auto-scanned
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500">
            Uncheck items that aren't project-related. Tax is recalculated proportionally.
          </p>
          {aiParsed && items.length > 0 ? (
            <ReceiptItemizer
              items={items}
              rawTax={rawTax}
              rawSubtotal={rawSubtotal}
              onChange={setItems}
            />
          ) : (
            <ExpenseItemEditor value={items} onChange={setItems} />
          )}
        </section>

        {/* Totals */}
        <section className="rounded-xl border border-surface-darker bg-white p-6 space-y-4">
          <h2 className="text-lg font-semibold text-gray-900">Totals</h2>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Raw Subtotal</label>
              <input
                type="number"
                value={(rawSubtotal / 100).toFixed(2)}
                onChange={(e) => setRawSubtotal(Math.round(parseFloat(e.target.value || '0') * 100))}
                step={0.01}
                min={0}
                className={`w-full ${inputClass}`}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Tax</label>
              <input
                type="number"
                value={(rawTax / 100).toFixed(2)}
                onChange={(e) => setRawTax(Math.round(parseFloat(e.target.value || '0') * 100))}
                step={0.01}
                min={0}
                className={`w-full ${inputClass}`}
              />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">Raw Total</label>
              <input
                type="number"
                value={(rawTotal / 100).toFixed(2)}
                onChange={(e) => setRawTotal(Math.round(parseFloat(e.target.value || '0') * 100))}
                step={0.01}
                min={0}
                className={`w-full ${inputClass}`}
              />
            </div>
          </div>

          {/* Calculated project totals */}
          <div className="mt-4 rounded-lg bg-primary-50 border border-primary-200 p-4">
            <h3 className="text-sm font-semibold text-primary-800 mb-2">Project Amounts (calculated)</h3>
            <div className="grid grid-cols-3 gap-4 text-sm">
              <div>
                <span className="text-primary-600">Project Subtotal</span>
                <p className="text-lg font-bold text-primary-900 tabular-nums">{formatCents(project.projectSubtotal)}</p>
              </div>
              <div>
                <span className="text-primary-600">Project Tax</span>
                <p className="text-lg font-bold text-primary-900 tabular-nums">{formatCents(project.projectTax)}</p>
              </div>
              <div>
                <span className="text-primary-600">Project Total</span>
                <p className="text-lg font-bold text-primary-900 tabular-nums">{formatCents(project.projectTotal)}</p>
              </div>
            </div>
          </div>
        </section>

        {/* Submit */}
        <div className="flex items-center justify-end gap-3">
          <Link to="/admin/expenses">
            <Button type="button" variant="secondary">
              Cancel
            </Button>
          </Link>
          <Button type="submit" loading={saving}>
            {isNew ? 'Create Expense' : 'Save Changes'}
          </Button>
        </div>
      </form>
    </div>
  )
}
