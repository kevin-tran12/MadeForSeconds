import type { Ingredient } from '../../lib/types'
import { Button } from '../ui/Button'

interface IngredientEditorProps {
  value: Ingredient[]
  onChange: (ingredients: Ingredient[]) => void
}

export function IngredientEditor({ value, onChange }: IngredientEditorProps) {
  function add() {
    onChange([...value, { amount: '', unit: '', item: '' }])
  }

  function remove(index: number) {
    onChange(value.filter((_, i) => i !== index))
  }

  function update(index: number, field: keyof Ingredient, text: string) {
    onChange(value.map((ing, i) => (i === index ? { ...ing, [field]: text } : ing)))
  }

  return (
    <div className="flex flex-col gap-2">
      {value.map((ing, i) => (
        <div key={i} className="flex gap-2">
          <input
            type="text"
            value={ing.amount}
            onChange={(e) => update(i, 'amount', e.target.value)}
            placeholder="Amount"
            className="w-20 rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
          />
          <input
            type="text"
            value={ing.unit}
            onChange={(e) => update(i, 'unit', e.target.value)}
            placeholder="Unit"
            className="w-24 rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
          />
          <input
            type="text"
            value={ing.item}
            onChange={(e) => update(i, 'item', e.target.value)}
            placeholder="Ingredient"
            className="flex-1 rounded-lg border border-gray-300 px-2 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
          />
          <button
            type="button"
            onClick={() => remove(i)}
            className="rounded-lg px-2 text-gray-400 hover:text-red-500"
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
