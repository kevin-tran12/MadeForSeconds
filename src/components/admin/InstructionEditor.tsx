import { useEffect, useRef } from 'react'
import type { Instruction } from '../../lib/types'
import { Button } from '../ui/Button'

interface InstructionEditorProps {
  value: Instruction[]
  onChange: (instructions: Instruction[]) => void
}

function autoResize(el: HTMLTextAreaElement) {
  el.style.height = 'auto'
  el.style.height = el.scrollHeight + 'px'
}

export function InstructionEditor({ value, onChange }: InstructionEditorProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  // Resize all textareas when value changes (handles pre-filled content on load)
  useEffect(() => {
    containerRef.current?.querySelectorAll('textarea').forEach((el) => autoResize(el))
  }, [value])

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

  function updateTip(index: number, tip: string) {
    onChange(value.map((inst, i) => (i === index ? { ...inst, tip: tip || null } : inst)))
  }

  function removeTip(index: number) {
    onChange(value.map((inst, i) => (i === index ? { ...inst, tip: null } : inst)))
  }

  return (
    <div ref={containerRef} className="flex flex-col gap-8">
      {value.map((inst, i) => (
        <div key={i} className="flex gap-3">
          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-100 text-sm font-bold text-primary-700 mt-1.5">
            {inst.step}
          </span>
          <div className="flex flex-1 flex-col gap-1.5">
            <textarea
              value={inst.text}
              onChange={(e) => updateText(i, e.target.value)}
              onInput={(e) => autoResize(e.currentTarget)}
              placeholder={`Step ${inst.step}…`}
              rows={1}
              style={{ overflow: 'hidden' }}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-100"
            />
            {inst.tip != null ? (
              <div className="flex gap-2">
                <textarea
                  value={inst.tip}
                  onChange={(e) => updateTip(i, e.target.value)}
                  onInput={(e) => autoResize(e.currentTarget)}
                  placeholder="Tip or visual cue for this step…"
                  rows={1}
                  style={{ overflow: 'hidden' }}
                  className="flex-1 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm focus:border-amber-400 focus:outline-none focus:ring-2 focus:ring-amber-100"
                />
                <button
                  type="button"
                  onClick={() => removeTip(i)}
                  className="self-start rounded-lg p-1 text-amber-400 hover:text-red-500"
                  aria-label="Remove tip"
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => updateTip(i, '')}
                className="self-start text-xs text-gray-400 hover:text-amber-600 transition-colors"
              >
                + Add tip
              </button>
            )}
          </div>
          <button
            type="button"
            onClick={() => remove(i)}
            className="self-start rounded-lg p-1 text-gray-400 hover:text-red-500 mt-1.5"
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
