import { useState } from 'react'
import type { NutritionEntry } from '../../lib/types'
import { Button } from '../ui/Button'

interface NutritionEditorProps {
  value: NutritionEntry[]
  onChange: (entries: NutritionEntry[]) => void
}

type NutritionRow = { label: string; value: string; unit: string }

function toRows(nutrition: NutritionEntry[]): NutritionRow[] {
  return nutrition.map((n) => ({ label: n.label, value: String(n.value), unit: n.unit }))
}

function toEntries(rows: NutritionRow[]): NutritionEntry[] {
  return rows
    .filter((r) => r.label.trim() && r.value !== '')
    .map((r) => ({ label: r.label.trim(), value: parseFloat(r.value) || 0, unit: r.unit.trim() }))
}

export function NutritionEditor({ value, onChange }: NutritionEditorProps) {
  const [rows, setRows] = useState<NutritionRow[]>(() => toRows(value))

  function update(i: number, field: keyof NutritionRow, val: string) {
    const next = rows.map((r, idx) => (idx === i ? { ...r, [field]: val } : r))
    setRows(next)
    onChange(toEntries(next))
  }

  function add() {
    const next = [...rows, { label: '', value: '', unit: '' }]
    setRows(next)
  }

  function remove(i: number) {
    const next = rows.filter((_, idx) => idx !== i)
    setRows(next)
    onChange(toEntries(next))
  }

  return (
    <div className="flex flex-col gap-2">
      {rows.length > 0 && (
        <div className="grid grid-cols-[1fr_5rem_4rem_2rem] gap-2 px-1">
          <span className="text-xs font-medium text-gray-500">Nutrient</span>
          <span className="text-xs font-medium text-gray-500">Amount</span>
          <span className="text-xs font-medium text-gray-500">Unit</span>
          <span />
        </div>
      )}
      {rows.map((row, i) => (
        <div key={i} className="grid grid-cols-[1fr_5rem_4rem_2rem] items-center gap-2">
          <input
            type="text"
            value={row.label}
            onChange={(e) => update(i, 'label', e.target.value)}
            placeholder="e.g. Calories, Sodium, Vitamin C"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
          />
          <input
            type="number"
            min="0"
            step="any"
            value={row.value}
            onChange={(e) => update(i, 'value', e.target.value)}
            placeholder="—"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
          />
          <input
            type="text"
            value={row.unit}
            onChange={(e) => update(i, 'unit', e.target.value)}
            placeholder="g / mg"
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
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
        + Add item
      </Button>
    </div>
  )
}
