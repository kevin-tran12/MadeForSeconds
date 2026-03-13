import { Link } from 'react-router-dom'
import { useRecipes } from '../hooks/useRecipes'
import { useCategories } from '../hooks/useCategories'
import { RecipeGrid } from '../components/recipe/RecipeGrid'

export function HomePage() {
  const { recipes, loading } = useRecipes()
  const { categories } = useCategories()
  const featured = recipes.slice(0, 6)

  return (
    <div>
      {/* Hero */}
      <section className="bg-gradient-to-b from-primary-50 to-surface py-20 text-center">
        <div className="mx-auto max-w-2xl px-4">
          <h1 className="font-display text-4xl font-bold text-gray-900 md:text-5xl lg:text-6xl">
            Made for <span className="text-primary-600">Seconds</span>
          </h1>
          <p className="mt-4 text-lg text-gray-600">
            A personal collection of recipes worth making again and again.
          </p>
          <Link
            to="/recipes"
            className="mt-8 inline-block rounded-xl bg-primary-600 px-8 py-3 text-base font-semibold text-white shadow-sm transition-colors hover:bg-primary-700"
          >
            Browse recipes
          </Link>
        </div>
      </section>

      {/* Category quick-links */}
      {categories.length > 0 && (
        <section className="mx-auto max-w-6xl px-4 py-8">
          <div className="flex flex-wrap gap-2">
            {categories.map((cat) => (
              <Link
                key={cat}
                to={`/recipes?category=${encodeURIComponent(cat)}`}
                className="rounded-full bg-surface-dark px-4 py-1.5 text-sm font-medium capitalize text-gray-700 transition-colors hover:bg-primary-100 hover:text-primary-700"
              >
                {cat}
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Featured recipes */}
      <section className="mx-auto max-w-6xl px-4 pb-16">
        <div className="mb-6 flex items-center justify-between">
          <h2 className="font-display text-2xl font-bold text-gray-900">Latest recipes</h2>
          <Link to="/recipes" className="text-sm font-medium text-primary-600 hover:text-primary-700">
            View all →
          </Link>
        </div>
        <RecipeGrid recipes={featured} loading={loading} emptyMessage="No recipes published yet." />
      </section>
    </div>
  )
}
