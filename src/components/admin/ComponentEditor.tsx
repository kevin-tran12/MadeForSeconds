import type { RecipeComponent } from '../../lib/types'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { IngredientEditor } from './IngredientEditor'
import { InstructionEditor } from './InstructionEditor'

const MAX_COMPONENTS = 5

function emptyComponent(): RecipeComponent {
  return {
    title: '',
    description: null,
    ingredients: [{ amount: '', unit: '', item: '' }],
    instructions: [{ step: 1, text: '' }],
    prep_time_minutes: null,
    cook_time_minutes: null,
    yield_description: null,
  }
}

interface ComponentEditorProps {
  value: RecipeComponent[]
  onChange: (components: RecipeComponent[]) => void
}

export function ComponentEditor({ value, onChange }: ComponentEditorProps) {
  function add() {
    if (value.length >= MAX_COMPONENTS) return
    onChange([...value, emptyComponent()])
  }

  function remove(index: number) {
    onChange(value.filter((_, i) => i !== index))
  }

  function update<K extends keyof RecipeComponent>(index: number, field: K, val: RecipeComponent[K]) {
    onChange(value.map((c, i) => (i === index ? { ...c, [field]: val } : c)))
  }

  return (
    <div className="flex flex-col gap-4">
      {value.map((comp, i) => (
        <div key={i} className="rounded-xl border border-primary-100 bg-primary-50/30 p-5">
          {/* Component header */}
          <div className="mb-4 flex items-center justify-between">
            <span className="text-sm font-bold text-primary-700 uppercase tracking-widest">
              Component {i + 1}
            </span>
            {value.length > 1 && (
              <button
                type="button"
                onClick={() => remove(i)}
                className="text-xs font-medium text-red-400 hover:text-red-600 transition-colors"
              >
                Remove
              </button>
            )}
          </div>

          <div className="flex flex-col gap-4">
            {/* Title */}
            <Input
              id={`comp-title-${i}`}
              label="Component title *"
              value={comp.title}
              onChange={(e) => update(i, 'title', e.target.value)}
              placeholder="e.g. Hainanese Chicken Rice"
              required
            />

            {/* Description */}
            <div className="flex flex-col gap-1">
              <label className="text-sm font-medium text-gray-700">Description</label>
              <textarea
                rows={2}
                value={comp.description ?? ''}
                onChange={(e) => update(i, 'description', e.target.value || null)}
                placeholder="Brief description of this component…"
                className="resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
              />
            </div>

            {/* Timing + yield */}
            <div className="grid grid-cols-3 gap-3">
              <Input
                id={`comp-prep-${i}`}
                label="Prep (min)"
                type="number"
                min="0"
                value={comp.prep_time_minutes ?? ''}
                onChange={(e) => update(i, 'prep_time_minutes', e.target.value ? parseInt(e.target.value) : null)}
              />
              <Input
                id={`comp-cook-${i}`}
                label="Cook (min)"
                type="number"
                min="0"
                value={comp.cook_time_minutes ?? ''}
                onChange={(e) => update(i, 'cook_time_minutes', e.target.value ? parseInt(e.target.value) : null)}
              />
              <Input
                id={`comp-yield-${i}`}
                label="Yield (optional)"
                value={comp.yield_description ?? ''}
                onChange={(e) => update(i, 'yield_description', e.target.value || null)}
                placeholder="About ½ cup"
              />
            </div>

            {/* Ingredients */}
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">Ingredients</p>
              <IngredientEditor
                value={comp.ingredients}
                onChange={(ings) => update(i, 'ingredients', ings)}
              />
            </div>

            {/* Instructions */}
            <div>
              <p className="mb-2 text-sm font-medium text-gray-700">Instructions</p>
              <InstructionEditor
                value={comp.instructions}
                onChange={(insts) => update(i, 'instructions', insts)}
              />
            </div>
          </div>
        </div>
      ))}

      {value.length < MAX_COMPONENTS && (
        <Button type="button" variant="secondary" size="sm" onClick={add} className="self-start">
          + Add component {value.length > 0 ? `(${value.length}/${MAX_COMPONENTS})` : ''}
        </Button>
      )}
      {value.length >= MAX_COMPONENTS && (
        <p className="text-xs text-gray-400">Maximum {MAX_COMPONENTS} components reached.</p>
      )}
    </div>
  )
}
