import { useState, useEffect } from 'react'
import { useNavigate, useParams, Link } from 'react-router-dom'
import { adminApi } from '../lib/api'
import type { Recipe, RecipeFormData } from '../lib/types'
import { RecipeForm } from '../components/admin/RecipeForm'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

export function AdminRecipeEditPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const isEdit = !!id

  const [recipe, setRecipe] = useState<Recipe | undefined>(undefined)
  const [loadingRecipe, setLoadingRecipe] = useState(isEdit)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    if (!isEdit) return

    async function load() {
      try {
        const all = await adminApi.listRecipes()
        const found = all.find((r) => r.id === id)
        if (!found) setLoadError('Recipe not found')
        else setRecipe(found)
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : 'Failed to load recipe')
      } finally {
        setLoadingRecipe(false)
      }
    }

    load()
  }, [id, isEdit])

  async function handleSubmit(data: RecipeFormData) {
    setIsSubmitting(true)
    try {
      if (isEdit && id) {
        await adminApi.updateRecipe(id, data)
      } else {
        await adminApi.createRecipe(data)
      }
      navigate('/admin/')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (loadingRecipe) return <LoadingSpinner size="lg" className="py-24" />

  if (loadError) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-24 text-center">
        <p className="text-red-600">{loadError}</p>
        <Link to="/admin/" className="mt-4 inline-block text-sm text-primary-600 hover:underline">
          ← Back to admin
        </Link>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-3xl px-4 py-10">
      <div className="mb-6 flex items-center gap-3">
        <Link to="/admin/" className="text-sm text-gray-500 hover:text-gray-700">
          ← Admin
        </Link>
        <span className="text-gray-300">/</span>
        <h1 className="font-display text-2xl font-bold text-gray-900">
          {isEdit ? 'Edit recipe' : 'New recipe'}
        </h1>
      </div>

      <RecipeForm
        recipe={recipe}
        onSubmit={handleSubmit}
        isSubmitting={isSubmitting}
      />
    </div>
  )
}
