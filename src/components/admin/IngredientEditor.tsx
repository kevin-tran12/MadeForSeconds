import type { Ingredient } from '../../lib/types'
import { Button } from '../ui/Button'

interface IngredientEditorProps {
  value: Ingredient[]
  onChange: (ingredients: Ingredient[]) => void
}

export function IngredientEditor({ value, onChange }: IngredientEditorProps) {
  function add() {
    onChange([...value, { amount: '', unit: '', item: '', group: undefined }])
  }

  function remove(index: number) {
    onChange(value.filter((_, i) => i !== index))
  }

  function update(index: number, field: keyof Ingredient, text: string) {
    onChange(value.map((ing, i) => (i === index ? { ...ing, [field]: text || undefined } : ing)))
  }

  return (
    <div className="flex flex-col gap-2">
      {value.length > 0 && (
        <div className="grid grid-cols-[5rem_6rem_1fr_7rem_2rem] gap-2 px-1">
          <span className="text-xs font-medium text-gray-500">Amount</span>
          <span className="text-xs font-medium text-gray-500">Unit</span>
          <span className="text-xs font-medium text-gray-500">Ingredient</span>
          <span className="text-xs font-medium text-gray-500">Section</span>
          <span />
        </div>
      )}
      {value.map((ing, i) => (
        <div key={i} className="grid grid-cols-[5rem_6rem_1fr_7rem_2rem] items-center gap-2">
          <input
            type="text"
            value={ing.amount}
            onChange={(e) => update(i, 'amount', e.target.value)}
            placeholder="1.5"
            className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
          />
          <input
            type="text"
            value={ing.unit}
            onChange={(e) => update(i, 'unit', e.target.value)}
            placeholder="cups"
            className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
          />
          <input
            type="text"
            value={ing.item}
            onChange={(e) => update(i, 'item', e.target.value)}
            placeholder="Ingredient name"
            className="rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
          />
          <input
            type="text"
            value={ing.group ?? ''}
            onChange={(e) => update(i, 'group', e.target.value)}
            placeholder="e.g. Broth"
            className="rounded-lg border border-dashed border-gray-300 bg-gray-50 px-2 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
          />
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
        + Add ingredient
      </Button>
    </div>
  )
}
