import { useState, type FormEvent, useRef } from 'react'
import type { Recipe, RecipeFormData, Difficulty, NutritionEntry } from '../../lib/types'
import { adminApi } from '../../lib/api'
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

type NutritionRow = { label: string; value: string; unit: string }

function initNutritionRows(nutrition: NutritionEntry[] | undefined): NutritionRow[] {
  if (!nutrition || nutrition.length === 0) return []
  return nutrition.map((n) => ({ label: n.label, value: String(n.value), unit: n.unit }))
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
  const [nutritionRows, setNutritionRows] = useState<NutritionRow[]>(
    () => initNutritionRows(recipe?.nutrition)
  )

  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    setError(null)
    setIsUploading(true)
    try {
      const { url } = await adminApi.uploadImage(file)
      setImageUrl(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setIsUploading(false)
    }
  }

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

  function addNutritionRow() {
    setNutritionRows((prev) => [...prev, { label: '', value: '', unit: '' }])
  }

  function removeNutritionRow(i: number) {
    setNutritionRows((prev) => prev.filter((_, idx) => idx !== i))
  }

  function updateNutritionRow(i: number, field: keyof NutritionRow, val: string) {
    setNutritionRows((prev) => prev.map((r, idx) => (idx === i ? { ...r, [field]: val } : r)))
  }

  function buildNutrition(): NutritionEntry[] {
    return nutritionRows
      .filter((r) => r.label.trim() && r.value !== '')
      .map((r) => ({ label: r.label.trim(), value: parseFloat(r.value) || 0, unit: r.unit.trim() }))
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
        nutrition: buildNutrition(),
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

        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <span className="text-sm font-medium text-gray-700">Recipe Image</span>
            <div className="flex items-start gap-4">
              <div className="group relative h-32 w-48 overflow-hidden rounded-lg border border-gray-300 bg-gray-50">
                {imageUrl ? (
                  <img src={imageUrl} alt="Preview" className="h-full w-full object-cover" />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-gray-400">
                    No image
                  </div>
                )}
                {isUploading && (
                  <div className="absolute inset-0 flex items-center justify-center bg-white/50">
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary-600 border-t-transparent" />
                  </div>
                )}
              </div>
              <div className="flex flex-col gap-2">
                <input
                  type="file"
                  ref={fileInputRef}
                  className="hidden"
                  accept="image/*"
                  onChange={handleFileUpload}
                />
                <Button type="button" variant="secondary" size="sm" onClick={() => fileInputRef.current?.click()} loading={isUploading}>
                  Upload image
                </Button>
                <p className="text-xs text-gray-500">Max 5MB. PNG, JPG, WEBP.</p>
              </div>
            </div>
          </div>
          <Input id="imageUrl" label="Image URL (fallback)" type="url" value={imageUrl} onChange={(e) => setImageUrl(e.target.value)} placeholder="https://…" />
        </div>

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

      <Section title="Nutrition (optional)">
        <p className="text-xs text-gray-400 -mt-2">Per serving. Add any nutrients — calories, macros, vitamins, minerals, etc.</p>
        <div className="flex flex-col gap-2">
          {nutritionRows.length > 0 && (
            <div className="grid grid-cols-[1fr_5rem_4rem_2rem] gap-2 px-1">
              <span className="text-xs font-medium text-gray-500">Nutrient</span>
              <span className="text-xs font-medium text-gray-500">Amount</span>
              <span className="text-xs font-medium text-gray-500">Unit</span>
              <span />
            </div>
          )}
          {nutritionRows.map((row, i) => (
            <div key={i} className="grid grid-cols-[1fr_5rem_4rem_2rem] items-center gap-2">
              <input
                type="text"
                value={row.label}
                onChange={(e) => updateNutritionRow(i, 'label', e.target.value)}
                placeholder="e.g. Calories, Sodium, Vitamin C"
                className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
              />
              <input
                type="number"
                min="0"
                step="any"
                value={row.value}
                onChange={(e) => updateNutritionRow(i, 'value', e.target.value)}
                placeholder="—"
                className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
              />
              <input
                type="text"
                value={row.unit}
                onChange={(e) => updateNutritionRow(i, 'unit', e.target.value)}
                placeholder="g / mg"
                className="rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
              />
              <button
                type="button"
                onClick={() => removeNutritionRow(i)}
                className="flex items-center justify-center rounded-lg p-1 text-gray-400 hover:text-red-500"
                aria-label="Remove"
              >
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))}
          <Button type="button" variant="secondary" size="sm" onClick={addNutritionRow} className="self-start mt-1">
            + Add item
          </Button>
        </div>
      </Section>

      <div className="flex gap-3">
        <Button type="submit" loading={isSubmitting} size="lg">
          {recipe ? 'Save changes' : 'Create recipe'}
        </Button>
      </div>
    </form>
  )
}
