import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { adminReportsApi } from '../lib/api'
import type { ReportSummary } from '../lib/api'
import { EXPENSE_CATEGORIES, formatCents } from '../lib/types-expense'
import { Button } from '../components/ui/Button'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

const currentYear = new Date().getFullYear()
const currentMonth = new Date().getMonth() + 1

const MONTHS = [
  { value: 0, label: 'Full Year' },
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

const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export function AdminReportsPage() {
  const [year, setYear] = useState(currentYear)
  const [month, setMonth] = useState(0) // 0 = full year
  const [summary, setSummary] = useState<ReportSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await adminReportsApi.getSummary(year, month || undefined)
      setSummary(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load report')
    } finally {
      setLoading(false)
    }
  }, [year, month])

  useEffect(() => { load() }, [load])

  function handleDownload(type: 'csv' | 'pdf') {
    const url = type === 'csv'
      ? adminReportsApi.downloadCsv(year, month || undefined)
      : adminReportsApi.downloadPdf(year, month || undefined)
    window.open(url, '_blank')
  }

  const maxMonthTotal = summary?.by_month
    ? Math.max(...summary.by_month.map((m) => m.total), 1)
    : 1

  return (
    <div className="mx-auto max-w-5xl px-4 py-10">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <Link to="/admin/expenses/" className="text-sm text-primary-600 hover:text-primary-700 mb-1 inline-block">
            ← Back to Expenses
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 font-display">Expense Reports</h1>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => handleDownload('csv')}>
            Download CSV
          </Button>
          <Button variant="secondary" onClick={() => handleDownload('pdf')}>
            Download PDF
          </Button>
        </div>
      </div>

      {/* Filters */}
      <div className="mb-6 flex items-center gap-3">
        <select
          value={year}
          onChange={(e) => setYear(Number(e.target.value))}
          className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
        >
          {YEARS.map((y) => (
            <option key={y} value={y}>{y}</option>
          ))}
        </select>
        <select
          value={month}
          onChange={(e) => setMonth(Number(e.target.value))}
          className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
        >
          {MONTHS.map((m) => (
            <option key={m.value} value={m.value}>{m.label}</option>
          ))}
        </select>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
      )}

      {loading ? (
        <LoadingSpinner size="lg" className="py-16" />
      ) : summary ? (
        <div className="space-y-6">
          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-4">
            <div className="rounded-xl border border-surface-darker bg-white p-5">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Project Expenses</p>
              <p className="mt-1 text-3xl font-bold text-gray-900 tabular-nums">
                {formatCents(summary.total_expenses)}
              </p>
            </div>
            <div className="rounded-xl border border-surface-darker bg-white p-5">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Tax Paid</p>
              <p className="mt-1 text-3xl font-bold text-gray-900 tabular-nums">
                {formatCents(summary.total_tax)}
              </p>
            </div>
            <div className="rounded-xl border border-surface-darker bg-white p-5">
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Purchases</p>
              <p className="mt-1 text-3xl font-bold text-gray-900">{summary.expense_count}</p>
            </div>
          </div>

          {/* Monthly bar chart (yearly view only) */}
          {!month && summary.by_month.length > 0 && (
            <div className="rounded-xl border border-surface-darker bg-white p-6">
              <h2 className="mb-4 text-lg font-semibold text-gray-900">Monthly Breakdown</h2>
              <div className="flex items-end gap-2 h-40">
                {summary.by_month.map((m) => {
                  const heightPct = maxMonthTotal > 0 ? (m.total / maxMonthTotal) * 100 : 0
                  const isCurrentMonth = m.month === currentMonth && year === currentYear
                  return (
                    <div key={m.month} className="flex flex-1 flex-col items-center gap-1">
                      <div className="w-full flex flex-col justify-end" style={{ height: '120px' }}>
                        {m.total > 0 && (
                          <div
                            className={`w-full rounded-t-md transition-all ${isCurrentMonth ? 'bg-primary-600' : 'bg-primary-300'}`}
                            style={{ height: `${Math.max(heightPct, 2)}%` }}
                            title={`${MONTH_NAMES[m.month - 1]}: ${formatCents(m.total)}`}
                          />
                        )}
                        {m.total === 0 && (
                          <div className="w-full border-t border-gray-200" style={{ height: '2px' }} />
                        )}
                      </div>
                      <span className="text-xs text-gray-500">{MONTH_NAMES[m.month - 1]}</span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Category breakdown */}
          {Object.keys(summary.by_category).length > 0 && (
            <div className="rounded-xl border border-surface-darker bg-white p-6">
              <h2 className="mb-4 text-lg font-semibold text-gray-900">By Category</h2>
              <table className="w-full text-sm">
                <thead className="border-b border-surface-darker text-left">
                  <tr>
                    <th className="pb-3 font-medium text-gray-600">Category</th>
                    <th className="pb-3 font-medium text-gray-600 text-right">Purchases</th>
                    <th className="pb-3 font-medium text-gray-600 text-right">Total</th>
                    <th className="pb-3 font-medium text-gray-600 text-right">Tax</th>
                    <th className="pb-3 font-medium text-gray-600 text-right">% of Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-darker">
                  {EXPENSE_CATEGORIES
                    .filter((c) => summary.by_category[c.value])
                    .map((c) => {
                      const cat = summary.by_category[c.value]
                      const pct = summary.total_expenses > 0
                        ? ((cat.total / summary.total_expenses) * 100).toFixed(1)
                        : '0'
                      return (
                        <tr key={c.value} className="hover:bg-surface/50">
                          <td className="py-3 font-medium text-gray-900">{c.label}</td>
                          <td className="py-3 text-right text-gray-600">{cat.count}</td>
                          <td className="py-3 text-right font-medium tabular-nums">{formatCents(cat.total)}</td>
                          <td className="py-3 text-right text-gray-600 tabular-nums">{formatCents(cat.tax)}</td>
                          <td className="py-3 text-right">
                            <div className="flex items-center justify-end gap-2">
                              <div className="w-16 h-1.5 rounded-full bg-gray-100 overflow-hidden">
                                <div
                                  className="h-full rounded-full bg-primary-500"
                                  style={{ width: `${pct}%` }}
                                />
                              </div>
                              <span className="text-gray-600 tabular-nums w-10 text-right">{pct}%</span>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                </tbody>
                <tfoot className="border-t-2 border-gray-300">
                  <tr>
                    <td className="pt-3 font-bold text-gray-900">Total</td>
                    <td className="pt-3 text-right font-bold">{summary.expense_count}</td>
                    <td className="pt-3 text-right font-bold tabular-nums">{formatCents(summary.total_expenses)}</td>
                    <td className="pt-3 text-right font-bold tabular-nums">{formatCents(summary.total_tax)}</td>
                    <td className="pt-3 text-right font-bold">100%</td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}

          {summary.expense_count === 0 && (
            <div className="rounded-xl border border-surface-darker bg-white p-12 text-center">
              <p className="text-gray-500">No expenses found for {summary.period}.</p>
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
