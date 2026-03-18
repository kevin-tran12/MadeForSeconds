import type { ExpenseItem } from '../../lib/types-expense'
import { formatCents } from '../../lib/types-expense'
import type { Recipe } from '../../lib/types'
import { Button } from '../ui/Button'

interface ExpenseItemEditorProps {
  value: ExpenseItem[]
  onChange: (items: ExpenseItem[]) => void
  recipes?: Recipe[]
}

export function ExpenseItemEditor({ value, onChange, recipes = [] }: ExpenseItemEditorProps) {
  function add() {
    onChange([...value, { name: '', quantity: 1, unit_price: 0, total_price: 0, project_related: true }])
  }

  function remove(index: number) {
    onChange(value.filter((_, i) => i !== index))
  }

  function update(index: number, field: keyof ExpenseItem, val: string | number | boolean | null) {
    onChange(
      value.map((item, i) => {
        if (i !== index) return item
        const updated = { ...item, [field]: val }
        // Auto-calculate total_price when quantity or unit_price changes
        if (field === 'quantity' || field === 'unit_price') {
          updated.total_price = Math.round(updated.quantity * updated.unit_price)
        }
        return updated
      })
    )
  }

  function updateRecipe(index: number, recipeId: string) {
    onChange(
      value.map((item, i) => {
        if (i !== index) return item
        if (!recipeId) {
          return { ...item, recipe_id: null, recipe_name: null }
        }
        const recipe = recipes.find((r) => r.id === recipeId)
        return { ...item, recipe_id: recipeId, recipe_name: recipe?.title ?? null }
      })
    )
  }

  const inputClass =
    'rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100'

  const hasRecipes = recipes.length > 0

  return (
    <div className="flex flex-col gap-2">
      {value.length > 0 && (
        <div className={`grid gap-2 px-1 ${hasRecipes ? 'grid-cols-[2.5rem_1fr_8rem_4rem_5rem_5rem_2rem]' : 'grid-cols-[2.5rem_1fr_4rem_5rem_5rem_5rem_2rem]'}`}>
          <span className="text-xs font-medium text-gray-500 text-center">Use</span>
          <span className="text-xs font-medium text-gray-500">Item Name</span>
          {hasRecipes && <span className="text-xs font-medium text-gray-500">Recipe</span>}
          <span className="text-xs font-medium text-gray-500">Qty</span>
          <span className="text-xs font-medium text-gray-500">Unit $</span>
          <span className="text-xs font-medium text-gray-500">Total</span>
          <span />
        </div>
      )}
      {value.map((item, i) => (
        <div
          key={i}
          className={`grid items-center gap-2 ${hasRecipes ? 'grid-cols-[2.5rem_1fr_8rem_4rem_5rem_5rem_2rem]' : 'grid-cols-[2.5rem_1fr_4rem_5rem_5rem_5rem_2rem]'} ${
            !item.project_related ? 'opacity-50' : ''
          }`}
        >
          <div className="flex justify-center">
            <input
              type="checkbox"
              checked={item.project_related}
              onChange={(e) => update(i, 'project_related', e.target.checked)}
              className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
            />
          </div>
          <input
            type="text"
            value={item.name}
            onChange={(e) => update(i, 'name', e.target.value)}
            placeholder="Item name"
            className={`${inputClass} ${!item.project_related ? 'line-through' : ''}`}
          />
          {hasRecipes && (
            <select
              value={item.recipe_id ?? ''}
              onChange={(e) => updateRecipe(i, e.target.value)}
              className={`${inputClass} text-xs`}
            >
              <option value="">—</option>
              {recipes.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.title}
                </option>
              ))}
            </select>
          )}
          <input
            type="number"
            value={item.quantity}
            onChange={(e) => update(i, 'quantity', parseFloat(e.target.value) || 0)}
            min={0}
            step={1}
            className={inputClass}
          />
          <input
            type="number"
            value={(item.unit_price / 100).toFixed(2)}
            onChange={(e) => update(i, 'unit_price', Math.round(parseFloat(e.target.value || '0') * 100))}
            min={0}
            step={0.01}
            className={inputClass}
          />
          <span className="text-sm text-gray-700 tabular-nums px-1">
            {formatCents(item.total_price)}
          </span>
          <button
            type="button"
            onClick={() => remove(i)}
            className="flex items-center justify-center rounded-lg p-1 text-gray-400 hover:text-red-500"
            aria-label="Remove"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      ))}
      <Button type="button" variant="secondary" size="sm" onClick={add} className="self-start mt-1">
        + Add item
      </Button>
    </div>
  )
}
