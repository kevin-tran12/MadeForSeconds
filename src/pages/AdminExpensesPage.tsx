import { useState, useEffect, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { adminExpenseApi } from '../lib/api'
import type { ExpenseSummary } from '../lib/types-expense'
import { EXPENSE_CATEGORIES, formatCents } from '../lib/types-expense'
import { ExpenseTable } from '../components/admin/ExpenseTable'
import { Button } from '../components/ui/Button'

const currentYear = new Date().getFullYear()
const currentMonth = new Date().getMonth() + 1

const MONTHS = [
  { value: 0, label: 'All months' },
  { value: 1, label: 'January' },
  { value: 2, label: 'February' },
  { value: 3, label: 'March' },
  { value: 4, label: 'April' },
  { value: 5, label: 'May' },
  { value: 6, label: 'June' },
  { value: 7, label: 'July' },
  { value: 8, label: 'August' },
  { value: 9, label: 'September' },
  { value: 10, label: 'October' },
  { value: 11, label: 'November' },
  { value: 12, label: 'December' },
]

const YEARS = Array.from({ length: 5 }, (_, i) => currentYear - i)

export function AdminExpensesPage() {
  const navigate = useNavigate()
  const [year, setYear] = useState(currentYear)
  const [month, setMonth] = useState(currentMonth)
  const [category, setCategory] = useState('')
  const [showVoided, setShowVoided] = useState(false)
  const [expenses, setExpenses] = useState<ExpenseSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await adminExpenseApi.list(
        year,
        month || undefined,
        category || undefined,
        showVoided ? 'voided' : 'active'
      )
      setExpenses(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load expenses')
    } finally {
      setLoading(false)
    }
  }, [year, month, category, showVoided])

  useEffect(() => {
    load()
  }, [load])

  async function handleVoid(id: string) {
    await adminExpenseApi.void(id)
    setExpenses((prev) => prev.filter((e) => e.id !== id))
  }

  // Running totals
  const totalProject = expenses.reduce((sum, e) => sum + e.project_total, 0)
  const totalTax = expenses.reduce((sum, e) => sum + e.project_tax, 0)

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <Link to="/admin" className="text-sm text-primary-600 hover:text-primary-700 mb-1 inline-block">
            ← Back to Dashboard
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 font-display">Expense Ledger</h1>
        </div>
        <div className="flex gap-2">
          <Link to="/admin/expenses/reports">
            <Button variant="secondary">Reports</Button>
          </Link>
          <Link to="/admin/expenses/new">
            <Button>+ New Expense</Button>
          </Link>
        </div>
      </div>

      {/* Summary cards */}
      {!loading && expenses.length > 0 && (
        <div className="mb-6 grid grid-cols-3 gap-4">
          <div className="rounded-xl border border-surface-darker bg-white p-4">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Project Total</p>
            <p className="mt-1 text-2xl font-bold text-gray-900 tabular-nums">{formatCents(totalProject)}</p>
          </div>
          <div className="rounded-xl border border-surface-darker bg-white p-4">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Tax Paid</p>
            <p className="mt-1 text-2xl font-bold text-gray-900 tabular-nums">{formatCents(totalTax)}</p>
          </div>
          <div className="rounded-xl border border-surface-darker bg-white p-4">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Purchases</p>
            <p className="mt-1 text-2xl font-bold text-gray-900">{expenses.length}</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
          className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
        >
          {YEARS.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>

        <select
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
          className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
        >
          {MONTHS.map((m) => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>

        <select
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
        >
          <option value="">All categories</option>
          {EXPENSE_CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>

        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={showVoided}
            onChange={(e) => setShowVoided(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
          />
          Show voided
        </label>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <ExpenseTable
        expenses={expenses}
        loading={loading}
        onView={(id) => navigate(`/admin/expenses/${id}`)}
        onVoid={handleVoid}
      />
    </div>
  )
}
