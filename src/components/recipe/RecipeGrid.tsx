import type { Recipe } from '../../lib/types'
import { RecipeCard } from './RecipeCard'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { EmptyState } from '../ui/EmptyState'

interface RecipeGridProps {
  recipes: Recipe[]
  loading: boolean
  emptyMessage?: string
  hasMore?: boolean
  loadingMore?: boolean
  onLoadMore?: () => void
}

export function RecipeGrid({
  recipes,
  loading,
  emptyMessage = 'No recipes found.',
  hasMore,
  loadingMore,
  onLoadMore,
}: RecipeGridProps) {
  if (loading) {
    return <LoadingSpinner size="lg" className="py-16" />
  }

  if (recipes.length === 0) {
    return <EmptyState title="Nothing here yet" message={emptyMessage} />
  }

  return (
    <div>
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
        {recipes.map((recipe) => (
          <RecipeCard key={recipe.id} recipe={recipe} />
        ))}
      </div>

      {hasMore && onLoadMore && (
        <div className="mt-8 flex justify-center">
          <button
            onClick={onLoadMore}
            disabled={loadingMore}
            className="inline-flex items-center gap-2 rounded-xl border border-control-border bg-control px-6 py-3 text-sm font-semibold text-content-body shadow-sm transition-all hover:-translate-y-0.5 hover:border-brand-border hover:text-brand hover:shadow-md disabled:pointer-events-none disabled:opacity-50"
          >
            {loadingMore ? (
              <>
                <LoadingSpinner size="sm" />
                Loading...
              </>
            ) : (
              'Load More'
            )}
          </button>
        </div>
      )}
    </div>
  )
}
