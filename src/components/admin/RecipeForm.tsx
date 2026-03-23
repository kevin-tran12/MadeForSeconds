import { useState, useEffect, type FormEvent, useRef } from 'react'
import type { Recipe, RecipeFormData, Difficulty, NutritionEntry, RecipeComponent } from '../../lib/types'
import { adminApi } from '../../lib/api'
import { useCategories } from '../../hooks/useCategories'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { IngredientEditor } from './IngredientEditor'
import { InstructionEditor } from './InstructionEditor'
import { NutritionEditor } from './NutritionEditor'
import { ComponentEditor } from './ComponentEditor'

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

function defaultComponent(): RecipeComponent {
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
  const { categories: availableCategories } = useCategories()

  // Strip categories not in the admin-configured list (e.g. from AI import or stale data)
  useEffect(() => {
    if (availableCategories.length > 0 && categories.length > 0) {
      const valid = categories.filter(c => availableCategories.includes(c))
      if (valid.length !== categories.length) {
        setCategories(valid)
      }
    }
  }, [availableCategories]) // eslint-disable-line react-hooks/exhaustive-deps

  const [ingredients, setIngredients] = useState(
    recipe?.ingredients ?? [{ amount: '', unit: '', item: '' }]
  )
  const [instructions, setInstructions] = useState(
    recipe?.instructions ?? [{ step: 1, text: '' }]
  )
  const [nutrition, setNutrition] = useState<NutritionEntry[]>(recipe?.nutrition ?? [])

  // Multi-component mode
  const hasExistingComponents = (recipe?.components?.length ?? 0) > 0
  const [multiComponent, setMultiComponent] = useState(hasExistingComponents)
  const [components, setComponents] = useState<RecipeComponent[]>(
    hasExistingComponents ? recipe!.components! : [defaultComponent()]
  )

  const [receiptUrls, setReceiptUrls] = useState<string[]>(recipe?.receipt_urls ?? [])
  const [isUploadingReceipt, setIsUploadingReceipt] = useState(false)
  const receiptInputRef = useRef<HTMLInputElement>(null)

  const [isUploading, setIsUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  async function handleReceiptUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return

    setError(null)
    setIsUploadingReceipt(true)
    try {
      const { url } = await adminApi.uploadReceipt(file)
      setReceiptUrls((prev) => [...prev, url])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Receipt upload failed')
    } finally {
      setIsUploadingReceipt(false)
      if (receiptInputRef.current) receiptInputRef.current.value = ''
    }
  }

  async function handleReceiptDelete(url: string) {
    if (recipe?.id) {
      try {
        await adminApi.deleteReceipt(recipe.id, url)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to delete receipt')
        return
      }
    }
    setReceiptUrls((prev) => prev.filter((u) => u !== url))
  }

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

  function toggleCategory(cat: string) {
    setCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    )
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)

    if (!title.trim()) return setError('Title is required')

    if (multiComponent) {
      if (components.length === 0) return setError('At least one component is required')
      if (!components[0].title.trim()) return setError('First component needs a title')
      if (components[0].ingredients.length === 0 || !components[0].ingredients[0].item)
        return setError('First component needs at least one ingredient')
      if (components[0].instructions.length === 0 || !components[0].instructions[0].text)
        return setError('First component needs at least one instruction step')
    } else {
      if (ingredients.length === 0 || !ingredients[0].item) return setError('At least one ingredient is required')
      if (instructions.length === 0 || !instructions[0].text) return setError('At least one instruction step is required')
    }

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
        ingredients: multiComponent ? [] : ingredients,
        instructions: multiComponent ? [] : instructions,
        nutrition,
        components: multiComponent ? components : null,
        receipt_urls: receiptUrls,
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

        {/* Multi-component toggle */}
        <div className="rounded-lg border border-primary-100 bg-primary-50/40 px-4 py-3">
          <label className="flex cursor-pointer items-start gap-3">
            <div className="relative mt-0.5 shrink-0">
              <input
                type="checkbox"
                className="sr-only"
                checked={multiComponent}
                onChange={(e) => setMultiComponent(e.target.checked)}
              />
              <div className={`h-6 w-11 rounded-full transition-colors ${multiComponent ? 'bg-primary-600' : 'bg-gray-300'}`} />
              <div className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${multiComponent ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </div>
            <div>
              <span className="text-sm font-semibold text-gray-800">Multi-component recipe</span>
              <p className="mt-0.5 text-xs text-gray-500">
                For dishes made of separate parts — e.g. Hainanese Chicken Rice with poached chicken, rice, chili sauce, and ginger sauce. Up to 5 components.
              </p>
            </div>
          </label>
        </div>
      </Section>

      <Section title="Times & servings">
        <div className="grid grid-cols-3 gap-3">
          <Input id="prepTime" label="Prep (min)" type="number" min="0" value={prepTime} onChange={(e) => setPrepTime(e.target.value)} />
          <Input id="cookTime" label="Cook (min)" type="number" min="0" value={cookTime} onChange={(e) => setCookTime(e.target.value)} />
          <Input id="servings" label="Servings" type="number" min="1" value={servings} onChange={(e) => setServings(e.target.value)} />
        </div>
        {multiComponent && (
          <p className="text-xs text-gray-400">
            These are the overall totals shown in the recipe header. Each component has its own prep/cook times below.
          </p>
        )}
      </Section>

      <Section title="Categories">
        {availableCategories.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {availableCategories.map((cat) => {
              const selected = categories.includes(cat)
              return (
                <button
                  key={cat}
                  type="button"
                  onClick={() => toggleCategory(cat)}
                  className={`rounded-full px-3 py-1 text-sm font-medium capitalize transition-colors ${
                    selected
                      ? 'bg-primary-600 text-white hover:bg-primary-700'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {cat}
                </button>
              )
            })}
          </div>
        ) : (
          <p className="text-sm text-gray-400">No categories configured yet. Add some in Admin → Categories.</p>
        )}
      </Section>

      {multiComponent ? (
        <Section title="Components">
          <p className="text-xs text-gray-400 -mt-2">
            Each component is a self-contained sub-recipe with its own ingredients and steps.
          </p>
          <ComponentEditor value={components} onChange={setComponents} />
        </Section>
      ) : (
        <>
          <Section title="Ingredients">
            <IngredientEditor value={ingredients} onChange={setIngredients} />
          </Section>

          <Section title="Instructions">
            <InstructionEditor value={instructions} onChange={setInstructions} />
          </Section>
        </>
      )}

      <Section title="Nutrition (optional)">
        <p className="text-xs text-gray-400 -mt-2">Per serving. Add any nutrients — calories, macros, vitamins, minerals, etc.</p>
        <NutritionEditor value={nutrition} onChange={setNutrition} />
      </Section>

      <Section title="Purchase receipts (optional)">
        <p className="text-xs text-gray-400 -mt-2">Attach grocery or shopping receipts for this recipe. Images or PDFs accepted.</p>
        <input
          type="file"
          ref={receiptInputRef}
          className="hidden"
          accept="image/*,.pdf"
          onChange={handleReceiptUpload}
        />
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => receiptInputRef.current?.click()}
          loading={isUploadingReceipt}
        >
          Add receipt
        </Button>
        {receiptUrls.length > 0 && (
          <ul className="flex flex-col gap-2">
            {receiptUrls.map((url) => {
              const isPdf = url.toLowerCase().includes('.pdf') || url.toLowerCase().endsWith('pdf')
              return (
                <li key={url} className="flex items-center gap-3 rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                  {isPdf ? (
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-red-100 text-xs font-bold text-red-600">
                      PDF
                    </div>
                  ) : (
                    <img src={url} alt="Receipt" className="h-10 w-10 shrink-0 rounded object-cover" />
                  )}
                  <span className="flex-1 truncate text-xs text-gray-500">{url.split('/').pop()}</span>
                  <button
                    type="button"
                    onClick={() => handleReceiptDelete(url)}
                    className="shrink-0 rounded p-1 text-gray-400 hover:bg-red-50 hover:text-red-500"
                    aria-label="Remove receipt"
                  >
                    ✕
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </Section>

      <div className="flex gap-3">
        <Button type="submit" loading={isSubmitting} size="lg">
          {recipe ? 'Save changes' : 'Create recipe'}
        </Button>
      </div>
    </form>
  )
}
