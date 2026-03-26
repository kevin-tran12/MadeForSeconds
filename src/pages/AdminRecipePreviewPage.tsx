import { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { adminApi } from '../lib/api'
import type { Recipe } from '../lib/types'
import { RecipeDetail } from '../components/recipe/RecipeDetail'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

const STORAGE_KEY = 'recipe-preview-draft'

export function AdminRecipePreviewPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isDraft = id === 'draft'

  const [recipe, setRecipe] = useState<Recipe | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        if (isDraft) {
          const raw = localStorage.getItem(STORAGE_KEY)
          if (!raw) {
            setError('Preview data not found. Go back and click Preview again.')
            return
          }
          localStorage.removeItem(STORAGE_KEY)
          setRecipe(JSON.parse(raw) as Recipe)
        } else {
          const all = await adminApi.listRecipes()
          const found = all.find((r) => r.id === id)
          if (!found) setError('Recipe not found.')
          else setRecipe(found)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load recipe')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [id, isDraft])

  async function handleTogglePublish() {
    if (!recipe || isDraft) return
    try {
      const updated = await adminApi.updateRecipe(recipe.id, { published: !recipe.published })
      setRecipe(updated)
    } catch (err) {
      console.error('Failed to toggle publish:', err)
    }
  }

  if (loading) return <LoadingSpinner size="lg" className="py-24" />

  if (error || !recipe) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-24 text-center">
        <p className="text-red-600">{error ?? 'Recipe not found.'}</p>
        <button
          onClick={() => navigate(-1)}
          className="mt-4 inline-block text-sm text-primary-600 hover:underline"
        >
          ← Go back
        </button>
      </div>
    )
  }

  const editHref = recipe.id !== 'preview-draft' ? `/admin/edit/${recipe.id}` : '/admin'

  return (
    <div className="min-h-screen bg-white">
      {/* Admin banner */}
      <div className="sticky top-0 z-40 flex items-center justify-between border-b border-gray-200 bg-white/90 px-4 py-2.5 backdrop-blur-sm">
        <div className="flex items-center gap-3">
          <Link
            to={editHref}
            className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-800"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 1L3 7l6 6" />
            </svg>
            Back to edit
          </Link>
          <span className="text-gray-200">|</span>
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-widest text-gray-400">Preview</span>
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${recipe.published ? 'bg-green-100 text-green-700' : 'bg-amber-100 text-amber-700'}`}>
              {recipe.published ? 'Published' : 'Draft'}
            </span>
          </div>
        </div>

        {!isDraft && (
          <button
            onClick={handleTogglePublish}
            className={`rounded-lg px-3 py-1.5 text-sm font-medium transition-colors ${
              recipe.published
                ? 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                : 'bg-primary-600 text-white hover:bg-primary-700'
            }`}
          >
            {recipe.published ? 'Unpublish' : 'Publish'}
          </button>
        )}
      </div>

      {/* Full recipe */}
      <RecipeDetail recipe={recipe} />
    </div>
  )
}
