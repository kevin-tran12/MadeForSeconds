import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useRecipes } from '../hooks/useRecipes'
import { useCategories } from '../hooks/useCategories'
import { RecipeGrid } from '../components/recipe/RecipeGrid'

export function HomePage() {
  const { recipes, loading, error } = useRecipes()
  const { categories } = useCategories()
  const featured = recipes.slice(0, 6)
  const navigate = useNavigate()
  const [heroSearch, setHeroSearch] = useState('')

  function handleHeroSearch(e: React.FormEvent) {
    e.preventDefault()
    const q = heroSearch.trim()
    if (q) navigate(`/recipes?q=${encodeURIComponent(q)}`)
    else navigate('/recipes')
  }

  return (
    <div>
      {/* Hero */}
      <section
        className="relative overflow-hidden bg-cover bg-center py-28 md:py-44"
        style={{ backgroundImage: "url('/hero-bg.jpg')" }}
      >
        {/* Dark overlay */}
        <div className="absolute inset-0 bg-black/60" />

        <div className="relative mx-auto max-w-4xl px-4 text-center">
          <h1 className="font-display text-5xl font-bold tracking-tight text-white md:text-7xl">
            Made for <span className="text-primary-300">Seconds</span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-white/85 md:text-xl">
            The kitchen's a mess. The food's good.
          </p>

          {/* Hero search */}
          <form onSubmit={handleHeroSearch} className="mx-auto mt-8 flex w-full max-w-xl items-center gap-2 rounded-2xl bg-white/10 p-1.5 ring-1 ring-white/20 backdrop-blur-sm">
            <div className="flex flex-1 items-center gap-2 rounded-xl bg-white px-4 py-2.5">
              <svg className="h-5 w-5 shrink-0 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
              </svg>
              <input
                type="text"
                value={heroSearch}
                onChange={(e) => setHeroSearch(e.target.value)}
                placeholder="Search recipes…"
                className="flex-1 bg-transparent text-sm text-gray-900 placeholder-gray-400 outline-none"
              />
            </div>
            <button
              type="submit"
              className="rounded-xl bg-primary-500 px-5 py-2.5 text-sm font-semibold text-white transition-all hover:bg-primary-400 active:scale-95"
            >
              Search
            </button>
          </form>

          <div className="mt-6 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link
              to="/recipes"
              className="rounded-xl bg-primary-500 px-8 py-4 text-lg font-semibold text-white shadow-lg shadow-black/30 transition-all hover:bg-primary-400 hover:shadow-xl active:scale-95"
            >
              Browse recipes
            </Link>
            <Link
              to="/about"
              className="rounded-xl border border-white/50 px-8 py-4 text-lg font-semibold text-white transition-all hover:bg-white/10 active:scale-95"
            >
              Learn more
            </Link>
          </div>
        </div>
      </section>

      {/* Category quick-links */}
      {categories.length > 0 && (
        <section className="mx-auto max-w-6xl px-4 py-12">
          <div className="mb-8 text-center md:text-left">
            <h2 className="font-display text-xl font-bold tracking-tight text-gray-900 uppercase">
              Browse by Category
            </h2>
            <div className="mt-2 h-1 w-12 bg-primary-500 rounded-full mx-auto md:mx-0" />
          </div>
          <div className="flex flex-wrap justify-center md:justify-start gap-3">
            {categories.map((cat) => (
              <Link
                key={cat}
                to={`/recipes?category=${encodeURIComponent(cat)}`}
                className="group flex items-center gap-2 rounded-2xl bg-surface-dark border border-surface-darker px-6 py-3 text-base font-medium capitalize text-gray-700 transition-all hover:bg-primary-600 hover:text-white hover:shadow-lg hover:shadow-primary-100 active:scale-95"
              >
                {cat}
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Featured recipes */}
      <section className="mx-auto max-w-6xl px-4 pb-24">
        <div className="mb-8 flex items-center justify-between border-b border-gray-100 pb-4">
          <h2 className="font-display text-2xl font-bold text-gray-900 md:text-3xl">Latest recipes</h2>
          <Link to="/recipes" className="group flex items-center gap-1 text-sm font-bold text-primary-600 transition-colors hover:text-primary-700">
            View all 
            <svg className="h-4 w-4 transition-transform group-hover:translate-x-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
            </svg>
          </Link>
        </div>
        {error && (
          <p className="mb-4 rounded-xl bg-red-50 px-4 py-3 text-sm text-red-600">{error}</p>
        )}
        <RecipeGrid recipes={featured} loading={loading} emptyMessage="No recipes published yet." />
      </section>
    </div>
  )
}
