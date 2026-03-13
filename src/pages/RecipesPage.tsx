import { useSearchParams } from 'react-router-dom'
import { useRecipes } from '../hooks/useRecipes'
import { useCategories } from '../hooks/useCategories'
import { RecipeGrid } from '../components/recipe/RecipeGrid'
import { RecipeSearch } from '../components/recipe/RecipeSearch'
import { CategoryFilter } from '../components/recipe/CategoryFilter'

export function RecipesPage() {
  const [params, setParams] = useSearchParams()
  const search = params.get('q') ?? ''
  const category = params.get('category') ?? ''

  const { recipes, loading } = useRecipes({ search, category: category || undefined })
  const { categories } = useCategories()

  function handleSearch(value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set('q', value)
    else next.delete('q')
    setParams(next, { replace: true })
  }

  function handleCategory(cat: string | null) {
    const next = new URLSearchParams(params)
    if (cat) next.set('category', cat)
    else next.delete('category')
    setParams(next, { replace: true })
  }

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="mb-6 font-display text-3xl font-bold text-gray-900">All Recipes</h1>

      {/* Filters */}
      <div className="mb-6 flex flex-col gap-3">
        <RecipeSearch value={search} onChange={handleSearch} />
        <CategoryFilter
          categories={categories}
          selected={category || null}
          onSelect={handleCategory}
        />
      </div>

      {/* Count */}
      {!loading && (
        <p className="mb-4 text-sm text-gray-500">
          {recipes.length} recipe{recipes.length !== 1 ? 's' : ''} found
        </p>
      )}

      <RecipeGrid
        recipes={recipes}
        loading={loading}
        emptyMessage="Try a different search or category."
      />
    </div>
  )
}
