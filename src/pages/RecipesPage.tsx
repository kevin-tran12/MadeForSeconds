import { useCallback, useEffect, useRef, useState } from 'react'
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
  const searchBy = params.get('search_by') ?? 'all'

  // Local input value updates instantly; URL (and API call) is debounced so
  // the grid doesn't reload on every keystroke and the page doesn't jump.
  const [localSearch, setLocalSearch] = useState(search)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Keep localSearch in sync if URL changes externally (e.g. nav from header)
  useEffect(() => { setLocalSearch(search) }, [search])

  const handleSearch = useCallback((value: string) => {
    setLocalSearch(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setParams((prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set('q', value)
        else next.delete('q')
        return next
      }, { replace: true })
    }, 400)
  }, [setParams])

  function handleSearchBy(value: string) {
    const next = new URLSearchParams(params)
    if (value && value !== 'all') next.set('search_by', value)
    else next.delete('search_by')
    setParams(next, { replace: true })
  }

  function handleCategory(cat: string | null) {
    const next = new URLSearchParams(params)
    if (cat) next.set('category', cat)
    else next.delete('category')
    setParams(next, { replace: true })
  }

  const { recipes, loading, error } = useRecipes({ search, category: category || undefined, searchBy })

  const { categories } = useCategories()

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="mb-6 font-display text-3xl font-bold text-gray-900">All Recipes</h1>

      {/* Filters */}
      <div className="mb-6 flex flex-col gap-3">
        <RecipeSearch
          value={localSearch}
          onChange={handleSearch}
          searchBy={searchBy}
          onSearchByChange={handleSearchBy}
        />
        <CategoryFilter
          categories={categories}
          selected={category || null}
          onSelect={handleCategory}
        />
      </div>

      {/* Error */}
      {error && (
        <p className="mb-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600">{error}</p>
      )}

      {/* Count — always reserve the row height to prevent layout shifts */}
      <p className="mb-4 text-sm text-gray-500 transition-opacity" style={{ opacity: loading ? 0.4 : 1 }}>
        {recipes.length} recipe{recipes.length !== 1 ? 's' : ''} found
      </p>

      <RecipeGrid
        recipes={recipes}
        loading={loading}
        emptyMessage="Try a different search or category."
      />
    </div>
  )
}
