import { useState, useEffect, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { adminApi } from '../lib/api'
import type { Recipe, RecipeFormData } from '../lib/types'
import { RecipeTable } from '../components/admin/RecipeTable'
import { Button } from '../components/ui/Button'
import { ImportRecipeModal } from '../components/admin/ImportRecipeModal'

export function AdminDashboardPage() {
  const navigate = useNavigate()
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showImport, setShowImport] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await adminApi.listRecipes()
      setRecipes(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load recipes')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleDelete(id: string) {
    await adminApi.deleteRecipe(id)
    setRecipes((prev) => prev.filter((r) => r.id !== id))
  }

  async function handleTogglePublish(recipe: Recipe) {
    const updated = await adminApi.updateRecipe(recipe.id, { published: !recipe.published })
    setRecipes((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
  }

  function handleImportSuccess(data: RecipeFormData) {
    setShowImport(false)
    navigate('/admin/new', { state: { prefill: data } })
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="font-display text-3xl font-bold text-gray-900">Admin</h1>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => setShowImport(true)}>Import recipe</Button>
          <Link to="/admin/new">
            <Button>+ New recipe</Button>
          </Link>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <RecipeTable
        recipes={recipes}
        loading={loading}
        onEdit={(id) => navigate(`/admin/edit/${id}`)}
        onDelete={handleDelete}
        onTogglePublish={handleTogglePublish}
      />

      {showImport && (
        <ImportRecipeModal
          onSuccess={handleImportSuccess}
          onClose={() => setShowImport(false)}
        />
      )}
    </div>
  )
}
