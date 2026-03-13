import type { Instruction } from '../../lib/types'
import { Button } from '../ui/Button'

interface InstructionEditorProps {
  value: Instruction[]
  onChange: (instructions: Instruction[]) => void
}

export function InstructionEditor({ value, onChange }: InstructionEditorProps) {
  function add() {
    onChange([...value, { step: value.length + 1, text: '' }])
  }

  function remove(index: number) {
    const updated = value.filter((_, i) => i !== index).map((inst, i) => ({ ...inst, step: i + 1 }))
    onChange(updated)
  }

  function updateText(index: number, text: string) {
    onChange(value.map((inst, i) => (i === index ? { ...inst, text } : inst)))
  }

  return (
    <div className="flex flex-col gap-3">
      {value.map((inst, i) => (
        <div key={i} className="flex gap-3">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-100 text-sm font-bold text-primary-700">
            {inst.step}
          </span>
          <textarea
            value={inst.text}
            onChange={(e) => updateText(i, e.target.value)}
            placeholder={`Step ${inst.step}…`}
            rows={2}
            className="flex-1 resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
          />
          <button
            type="button"
            onClick={() => remove(i)}
            className="self-start rounded-lg p-1 text-gray-400 hover:text-red-500"
            aria-label="Remove step"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      ))}
      <Button type="button" variant="secondary" size="sm" onClick={add} className="self-start mt-1">
        + Add step
      </Button>
    </div>
  )
}
