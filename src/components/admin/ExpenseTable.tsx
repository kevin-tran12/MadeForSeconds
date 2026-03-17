import type { ExpenseSummary } from '../../lib/types-expense'
import { EXPENSE_CATEGORIES, formatCents } from '../../lib/types-expense'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { EmptyState } from '../ui/EmptyState'

interface ExpenseTableProps {
  expenses: ExpenseSummary[]
  loading: boolean
  onView: (id: string) => void
  onVoid: (id: string) => Promise<void>
}

function categoryLabel(value: string): string {
  return EXPENSE_CATEGORIES.find((c) => c.value === value)?.label ?? value
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function ExpenseTable({ expenses, loading, onView, onVoid }: ExpenseTableProps) {
  if (loading) return <LoadingSpinner size="lg" className="py-16" />
  if (expenses.length === 0) {
    return <EmptyState title="No expenses yet" message="Add your first expense to start tracking." />
  }

  async function handleVoid(e: ExpenseSummary) {
    if (!confirm(`Void expense from "${e.vendor}" on ${formatDate(e.date)}? This cannot be undone.`)) return
    await onVoid(e.id)
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-surface-darker bg-white">
      <table className="w-full text-sm">
        <thead className="border-b border-surface-darker bg-surface text-left">
          <tr>
            <th className="px-4 py-3 font-medium text-gray-600">Date</th>
            <th className="px-4 py-3 font-medium text-gray-600">Vendor</th>
            <th className="px-4 py-3 font-medium text-gray-600">For</th>
            <th className="px-4 py-3 font-medium text-gray-600">Category</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-right">Project Total</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-right">Tax</th>
            <th className="px-4 py-3 font-medium text-gray-600">Status</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-darker">
          {expenses.map((exp) => (
            <tr
              key={exp.id}
              className={`hover:bg-surface/50 ${exp.status === 'voided' ? 'opacity-50' : ''}`}
            >
              <td className={`px-4 py-3 text-gray-700 ${exp.status === 'voided' ? 'line-through' : ''}`}>
                {formatDate(exp.date)}
              </td>
              <td className={`px-4 py-3 font-medium text-gray-900 ${exp.status === 'voided' ? 'line-through' : ''}`}>
                {exp.vendor}
              </td>
              <td className="px-4 py-3 text-gray-500 max-w-[200px] truncate">
                {exp.purpose || exp.description || '—'}
              </td>
              <td className="px-4 py-3">
                <Badge variant="default">{categoryLabel(exp.category)}</Badge>
              </td>
              <td className={`px-4 py-3 text-right font-medium tabular-nums ${exp.status === 'voided' ? 'line-through text-gray-400' : 'text-gray-900'}`}>
                {formatCents(exp.project_total)}
              </td>
              <td className="px-4 py-3 text-right text-gray-500 tabular-nums">
                {formatCents(exp.project_tax)}
              </td>
              <td className="px-4 py-3">
                <Badge variant={exp.status === 'active' ? 'success' : 'danger'}>
                  {exp.status === 'active' ? 'Active' : 'Voided'}
                </Badge>
              </td>
              <td className="px-4 py-3">
                <div className="flex items-center justify-end gap-2">
                  <Button variant="secondary" size="sm" onClick={() => onView(exp.id)}>
                    View
                  </Button>
                  {exp.status === 'active' && (
                    <Button variant="danger" size="sm" onClick={() => handleVoid(exp)}>
                      Void
                    </Button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
