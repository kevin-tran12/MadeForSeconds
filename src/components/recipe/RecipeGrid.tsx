import type { Recipe } from '../../lib/types'
import { RecipeCard } from './RecipeCard'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { EmptyState } from '../ui/EmptyState'

interface RecipeGridProps {
  recipes: Recipe[]
  loading: boolean
  emptyMessage?: string
}

export function RecipeGrid({ recipes, loading, emptyMessage = 'No recipes found.' }: RecipeGridProps) {
  if (loading) {
    return <LoadingSpinner size="lg" className="py-16" />
  }

  if (recipes.length === 0) {
    return <EmptyState title="Nothing here yet" message={emptyMessage} />
  }

  return (
    <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3">
      {recipes.map((recipe) => (
        <RecipeCard key={recipe.id} recipe={recipe} />
      ))}
    </div>
  )
}
