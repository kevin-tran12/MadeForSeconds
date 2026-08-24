import { Link, useParams } from 'react-router-dom'
import { useRecipe } from '../hooks/useRecipe'
import { RecipeDetail } from '../components/recipe/RecipeDetail'
import { LoadingSpinner } from '../components/ui/LoadingSpinner'
import { RecipeSchema } from '../components/seo/RecipeSchema'
import { usePageMeta } from '../hooks/usePageMeta'

function RecipeDetailMeta({ recipe }: { recipe: { title: string; description: string; image_url: string | null; slug: string } }) {
  usePageMeta({
    title: recipe.title,
    description: recipe.description || undefined,
    image: recipe.image_url,
    url: `https://madeforseconds.pages.dev/recipes/${recipe.slug}`,
    type: 'article',
  })
  return null
}

export function RecipeDetailPage() {
  const { slug } = useParams<{ slug: string }>()
  const { recipe, loading, error, isConnectionError } = useRecipe(slug)

  if (loading) {
    return <LoadingSpinner size="lg" className="py-24" />
  }

  // Connectivity failures are already explained by the global SiteStatusNotice
  // banner above — claiming the recipe "might not exist" here would be false,
  // and often the more alarming of the two messages.
  if (isConnectionError) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
        <div className="text-5xl">🍳</div>
        <h1 className="font-display text-2xl font-bold text-content">Couldn't load this recipe</h1>
        <p className="text-content-muted">Try again in a moment.</p>
      </div>
    )
  }

  if (error || !recipe) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-24 text-center">
        <div className="text-5xl">🍳</div>
        <h1 className="font-display text-2xl font-bold text-content">Recipe not found</h1>
        <p className="text-content-muted">This recipe might be private or no longer exists.</p>
        <Link
          to="/recipes/"
          className="mt-2 rounded-lg bg-primary-600 px-5 py-2.5 text-sm font-semibold text-on-brand hover:bg-primary-500"
        >
          Browse all recipes
        </Link>
      </div>
    )
  }

  return (
    <>
      <RecipeDetailMeta recipe={recipe} />
      <RecipeSchema recipe={recipe} />
      <RecipeDetail recipe={recipe} />
    </>
  )
}
