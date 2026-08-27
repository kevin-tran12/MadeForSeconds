import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useRecipes } from '../hooks/useRecipes'
import { useCategories } from '../hooks/useCategories'
import { RecipeGrid } from '../components/recipe/RecipeGrid'
import { RecipeSearch } from '../components/recipe/RecipeSearch'
import { CategoryFilter } from '../components/recipe/CategoryFilter'
import { RecipeSectionRow } from '../components/recipe/RecipeSectionRow'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

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

  const { categories } = useCategories()

  const {
    recipes, grouped, loading, loadingMore, error, isConnectionError, hasMore, loadMore, isFiltering, isFlat,
  } = useRecipes({ search, category: category || undefined, searchBy, forceFlat: categories.length === 0 })

  return (
    <div className="mx-auto max-w-6xl px-4 py-10">
      <h1 className="mb-6 font-display text-3xl font-bold text-content">All Recipes</h1>

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

      {/* A connectivity failure is already explained by the global
          SiteStatusNotice banner — don't repeat it in a raw fetch error. */}
      {error && !isConnectionError && (
        <p className="mb-4 rounded-xl border border-danger-border bg-danger-surface px-4 py-3 text-sm text-danger">{error}</p>
      )}

      {/* Content — grouped browse or flat filtered grid */}
      {isFlat ? (
        <>
          {/* Count row — only shown when actively filtering; keeps height reserved to avoid layout shifts */}
          <p className="mb-4 text-sm text-content-muted transition-opacity" style={{ opacity: loading ? 0.65 : 1 }}>
            {isFiltering ? <>{recipes.length}{hasMore ? '+' : ''} recipe{recipes.length !== 1 ? 's' : ''} found</> : <>&nbsp;</>}
          </p>
          <RecipeGrid
            recipes={recipes}
            loading={loading}
            emptyMessage={isFiltering ? "Try a different search or category." : "No recipes published yet."}
            hasMore={hasMore}
            loadingMore={loadingMore}
            onLoadMore={loadMore}
          />
        </>
      ) : loading ? (
        <LoadingSpinner size="lg" className="py-16" />
      ) : grouped ? (
        <div>
          {/* Recently Added */}
          <RecipeSectionRow
            title="Recently Added"
            recipes={grouped.recent}
          />

          {/* Category sections */}
          {grouped.groups.map((group) => (
            <RecipeSectionRow
              key={group.category}
              title={group.category}
              recipes={group.recipes}
              category={group.category}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}
