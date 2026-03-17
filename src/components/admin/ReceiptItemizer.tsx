import type { ExpenseItem } from '../../lib/types-expense'
import { formatCents, recalcProjectAmounts } from '../../lib/types-expense'

interface ReceiptItemizerProps {
  items: ExpenseItem[]
  rawTax: number
  rawSubtotal: number
  onChange: (items: ExpenseItem[]) => void
}

export function ReceiptItemizer({ items, rawTax, rawSubtotal, onChange }: ReceiptItemizerProps) {
  const { projectSubtotal, projectTax, projectTotal } = recalcProjectAmounts(items, rawTax, rawSubtotal)
  const selectedCount = items.filter((i) => i.project_related).length

  function toggle(index: number, checked: boolean) {
    onChange(items.map((item, i) => (i === index ? { ...item, project_related: checked } : item)))
  }

  function selectAll() {
    onChange(items.map((item) => ({ ...item, project_related: true })))
  }

  function deselectAll() {
    onChange(items.map((item) => ({ ...item, project_related: false })))
  }

  return (
    <div className="flex flex-col gap-3">
      {/* Bulk controls */}
      <div className="flex items-center justify-between">
        <span className="text-sm text-gray-500">
          {selectedCount} of {items.length} items selected as project-related
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={selectAll}
            className="text-xs font-medium text-primary-600 hover:text-primary-700"
          >
            Select all
          </button>
          <span className="text-gray-300">|</span>
          <button
            type="button"
            onClick={deselectAll}
            className="text-xs font-medium text-gray-500 hover:text-gray-700"
          >
            Deselect all
          </button>
        </div>
      </div>

      {/* Item list */}
      <div className="divide-y divide-gray-100 rounded-xl border border-gray-200 bg-white overflow-hidden">
        {items.map((item, i) => (
          <label
            key={i}
            className={`flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors ${
              item.project_related ? 'bg-white hover:bg-gray-50' : 'bg-gray-50 opacity-60'
            }`}
          >
            <input
              type="checkbox"
              checked={item.project_related}
              onChange={(e) => toggle(i, e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500 shrink-0"
            />
            <span className={`flex-1 text-sm ${item.project_related ? 'text-gray-900' : 'text-gray-400 line-through'}`}>
              {item.name}
              {item.quantity > 1 && (
                <span className="ml-1 text-xs text-gray-400">×{item.quantity}</span>
              )}
            </span>
            <span className={`text-sm tabular-nums shrink-0 ${item.project_related ? 'text-gray-700 font-medium' : 'text-gray-400'}`}>
              {formatCents(item.total_price)}
            </span>
          </label>
        ))}
      </div>

      {/* Running totals */}
      <div className="rounded-xl bg-primary-50 border border-primary-200 p-4">
        <div className="grid grid-cols-3 gap-4 text-sm">
          <div>
            <p className="text-xs text-primary-600 font-medium">Project Subtotal</p>
            <p className="text-lg font-bold text-primary-900 tabular-nums">{formatCents(projectSubtotal)}</p>
          </div>
          <div>
            <p className="text-xs text-primary-600 font-medium">Tax (proportional)</p>
            <p className="text-lg font-bold text-primary-900 tabular-nums">{formatCents(projectTax)}</p>
          </div>
          <div>
            <p className="text-xs text-primary-600 font-medium">Project Total</p>
            <p className="text-lg font-bold text-primary-900 tabular-nums">{formatCents(projectTotal)}</p>
          </div>
        </div>
      </div>
    </div>
  )
}
