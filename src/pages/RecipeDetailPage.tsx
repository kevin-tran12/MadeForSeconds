import { Link, useParams } from 'react-router-dom'
import { useRecipe } from '../hooks/useRecipe'
import { RecipeDetail } from '../components/recipe/RecipeDetail'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'

export function RecipeDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const { recipe, loading, error } = useRecipe(slug)

  if (loading) {
    return <LoadingSpinner size="lg" className="py-24" />
  }

  if (error || !recipe) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
        <div className="text-5xl">🍳</div>
        <h1 className="font-display text-2xl font-bold text-gray-900">Recipe not found</h1>
        <p className="text-gray-500">This recipe might be private or no longer exists.</p>
        <Link
          to="/recipes"
          className="mt-2 rounded-lg bg-primary-600 px-5 py-2.5 text-sm font-medium text-white hover:bg-primary-700"
        >
          Browse all recipes
        </Link>
      </div>
    )
  }

  return <RecipeDetail recipe={recipe} />
}
