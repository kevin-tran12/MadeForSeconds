import { useState, type FormEvent } from 'react'
import type { Recipe, RecipeFormData, Difficulty } from '../../lib/types'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { IngredientEditor } from './IngredientEditor'
import { InstructionEditor } from './InstructionEditor'

interface RecipeFormProps {
  recipe?: Recipe
  onSubmit: (data: RecipeFormData) => Promise<void>
  isSubmitting: boolean
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-surface-darker bg-white p-6">
      <h3 className="mb-4 font-display text-lg font-semibold text-gray-900">{title}</h3>
      <div className="flex flex-col gap-4">{children}</div>
    </div>
  )
}

export function RecipeForm({ recipe, onSubmit, isSubmitting }: RecipeFormProps) {
  const [title, setTitle] = useState(recipe?.title ?? '')
  const [description, setDescription] = useState(recipe?.description ?? '')
  const [imageUrl, setImageUrl] = useState(recipe?.image_url ?? '')
  const [difficulty, setDifficulty] = useState<Difficulty>(recipe?.difficulty ?? 'easy')
  const [prepTime, setPrepTime] = useState(String(recipe?.prep_time_minutes ?? 0))
  const [cookTime, setCookTime] = useState(String(recipe?.cook_time_minutes ?? 0))
  const [servings, setServings] = useState(String(recipe?.servings ?? 2))
  const [published, setPublished] = useState(recipe?.published ?? false)
  const [categories, setCategories] = useState<string[]>(recipe?.categories ?? [])
  const [categoryInput, setCategoryInput] = useState('')
  const [ingredients, setIngredients] = useState(
    recipe?.ingredients ?? [{ amount: '', unit: '', item: '' }]
  )
  const [instructions, setInstructions] = useState(
    recipe?.instructions ?? [{ step: 1, text: '' }]
  )
  const [error, setError] = useState<string | null>(null)

  function addCategory() {
    const trimmed = categoryInput.trim().toLowerCase()
    if (trimmed && !categories.includes(trimmed)) {
      setCategories([...categories, trimmed])
    }
    setCategoryInput('')
  }

  function removeCategory(cat: string) {
    setCategories(categories.filter((c) => c !== cat))
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)

    if (!title.trim()) return setError('Title is required')
    if (ingredients.length === 0 || !ingredients[0].item) return setError('At least one ingredient is required')
    if (instructions.length === 0 || !instructions[0].text) return setError('At least one instruction step is required')

    try {
      await onSubmit({
        title: title.trim(),
        description: description.trim(),
        image_url: imageUrl.trim() || null,
        difficulty,
        prep_time_minutes: parseInt(prepTime) || 0,
        cook_time_minutes: parseInt(cookTime) || 0,
        servings: parseInt(servings) || 1,
        published,
        categories,
        ingredients,
        instructions,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      {error && (
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <Section title="Basic info">
        <Input id="title" label="Title *" value={title} onChange={(e) => setTitle(e.target.value)} required />
        <div className="flex flex-col gap-1">
          <label htmlFor="description" className="text-sm font-medium text-gray-700">Description</label>
          <textarea
            id="description"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="resize-none rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
          />
        </div>
        <Input id="imageUrl" label="Image URL" type="url" value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="https://…" />
        <div className="flex flex-col gap-1">
          <label htmlFor="difficulty" className="text-sm font-medium text-gray-700">Difficulty</label>
          <select
            id="difficulty"
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value as Difficulty)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
          >
            <option value="easy">Easy</option>
            <option value="medium">Medium</option>
            <option value="hard">Hard</option>
          </select>
        </div>
        <label className="flex cursor-pointer items-center gap-3">
          <div className="relative">
            <input type="checkbox" className="sr-only" checked={published} onChange={(e) => setPublished(e.target.checked)} />
            <div className={`h-6 w-11 rounded-full transition-colors ${published ? 'bg-primary-600' : 'bg-gray-300'}`} />
            <div className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${published ? 'translate-x-5' : 'translate-x-0.5'}`} />
          </div>
          <span className="text-sm font-medium text-gray-700">Published</span>
        </label>
      </Section>

      <Section title="Times & servings">
        <div className="grid grid-cols-3 gap-3">
          <Input id="prepTime" label="Prep (min)" type="number" min="0" value={prepTime} onChange={(e) => setPrepTime(e.target.value)} />
          <Input id="cookTime" label="Cook (min)" type="number" min="0" value={cookTime} onChange={(e) => setCookTime(e.target.value)} />
          <Input id="servings" label="Servings" type="number" min="1" value={servings} onChange={(e) => setServings(e.target.value)} />
        </div>
      </Section>

      <Section title="Categories">
        <div className="flex gap-2">
          <input
            type="text"
            value={categoryInput}
            onChange={(e) => setCategoryInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCategory() } }}
            placeholder="Type and press Enter"
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
          />
          <Button type="button" variant="secondary" size="sm" onClick={addCategory}>Add</Button>
        </div>
        {categories.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {categories.map((cat) => (
              <button
                key={cat}
                type="button"
                onClick={() => removeCategory(cat)}
                className="inline-flex items-center gap-1 rounded-full bg-primary-100 px-3 py-1 text-sm font-medium text-primary-800 hover:bg-primary-200"
              >
                {cat} <span className="text-primary-500">×</span>
              </button>
            ))}
          </div>
        )}
      </Section>

      <Section title="Ingredients">
        <IngredientEditor value={ingredients} onChange={setIngredients} />
      </Section>

      <Section title="Instructions">
        <InstructionEditor value={instructions} onChange={setInstructions} />
      </Section>

      <div className="flex gap-3">
        <Button type="submit" loading={isSubmitting} size="lg">
          {recipe ? 'Save changes' : 'Create recipe'}
        </Button>
      </div>
    </form>
  )
}
