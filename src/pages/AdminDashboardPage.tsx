import { useState, useEffect, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { adminApi, adminSupporterApi } from '../lib/api'
import type { Recipe, RecipeFormData } from '../lib/types'
import { RecipeTable } from '../components/admin/RecipeTable'
import { SupporterModerationPanel } from '../components/admin/SupporterModerationPanel'
import { Button } from '../components/ui/Button'
import { ImportRecipeModal } from '../components/admin/ImportRecipeModal'

type Tab = 'recipes' | 'supporters' | 'expenses'

export function AdminDashboardPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('recipes')
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showImport, setShowImport] = useState(false)
  const [pendingCount, setPendingCount] = useState(0)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [data, pending] = await Promise.all([
        adminApi.listRecipes(),
        adminSupporterApi.listPending().catch(() => []),
      ])
      setRecipes(data)
      setPendingCount(pending.length)
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

  const tabClass = (t: Tab) =>
    `px-4 py-2 text-sm font-semibold rounded-lg transition-colors ${
      tab === t
        ? 'bg-white text-gray-900 shadow-sm'
        : 'text-gray-500 hover:text-gray-700'
    }`

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-1 rounded-xl bg-gray-100 p-1">
          <button className={tabClass('recipes')} onClick={() => setTab('recipes')}>
            Recipes
          </button>
          <button className={tabClass('supporters')} onClick={() => setTab('supporters')}>
            Supporters
            {pendingCount > 0 && (
              <span className="ml-1.5 rounded-full bg-amber-500 px-1.5 py-0.5 text-xs font-bold text-white">
                {pendingCount}
              </span>
            )}
          </button>
          <button className={tabClass('expenses')} onClick={() => setTab('expenses')}>
            Expenses
          </button>
        </div>

        {tab === 'recipes' && (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setShowImport(true)}>Import recipe</Button>
            <Link to="/admin/new">
              <Button>+ New recipe</Button>
            </Link>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-4 rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}

      {tab === 'recipes' && (
        <RecipeTable
          recipes={recipes}
          loading={loading}
          onEdit={(id) => navigate(`/admin/edit/${id}`)}
          onDelete={handleDelete}
          onTogglePublish={handleTogglePublish}
        />
      )}

      {tab === 'supporters' && <SupporterModerationPanel />}

      {tab === 'expenses' && (
        <div className="rounded-xl border border-surface-darker bg-white p-8 text-center">
          <h3 className="text-lg font-semibold text-gray-900 mb-2">Expense Ledger</h3>
          <p className="text-sm text-gray-500 mb-4">Track purchases, upload receipts, and generate tax reports.</p>
          <Link to="/admin/expenses">
            <Button>Open Expense Ledger</Button>
          </Link>
        </div>
      )}

      {showImport && (
        <ImportRecipeModal
          onSuccess={handleImportSuccess}
          onClose={() => setShowImport(false)}
        />
      )}
    </div>
  )
}
