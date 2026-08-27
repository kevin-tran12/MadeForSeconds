import { Link } from 'react-router-dom'
import { useRecipes } from '../hooks/useRecipes'
import { useCategories } from '../hooks/useCategories'
import { usePageContent } from '../hooks/usePageContent'
import { RecipeGrid } from '../components/recipe/RecipeGrid'
import { SearchWithSuggestions } from '../components/search/SearchWithSuggestions'

const HOME_DEFAULTS = {
  hero_title: 'Made for Seconds',
  hero_subtitle: "The kitchen's a mess. The food's good.",
}

export function HomePage() {
  const { recipes, loading, error, isConnectionError } = useRecipes({ forceFlat: true })
  const { categories } = useCategories()
  const page = usePageContent('home', HOME_DEFAULTS)
  const featured = recipes.slice(0, 6)

  return (
    <div>
      {/* Hero */}
      <section
        className="relative overflow-hidden bg-cover bg-center py-28 md:py-44"
        style={{ backgroundImage: "url('/hero-bg.jpg')" }}
      >
        {/* Dark overlay */}
        <div className="absolute inset-0 bg-hero-overlay" />

        <div className="relative mx-auto max-w-4xl px-4 text-center">
          <h1 className="font-display text-5xl font-bold tracking-tight text-hero-content md:text-7xl">
            {page.hero_title}
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-hero-content/90 md:text-xl">
            {page.hero_subtitle}
          </p>

          {/* Hero search */}
          <div className="mx-auto mt-8 w-full max-w-xl rounded-2xl bg-hero-panel p-1.5 ring-1 ring-hero-border backdrop-blur-sm">
            <SearchWithSuggestions />
          </div>

          <div className="mt-6 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link
              to="/recipes/"
              className="rounded-xl bg-primary-500 px-8 py-4 text-lg font-semibold text-on-brand shadow-lg shadow-black/30 transition-all hover:bg-primary-400 hover:shadow-xl active:scale-95"
            >
              Browse recipes
            </Link>
            <Link
              to="/about/"
              className="rounded-xl border border-hero-border px-8 py-4 text-lg font-semibold text-hero-content transition-all hover:bg-hero-panel active:scale-95"
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
            <h2 className="font-display text-xl font-bold tracking-tight text-content uppercase">
              Browse by Category
            </h2>
            <div className="mt-2 h-1 w-12 bg-primary-500 rounded-full mx-auto md:mx-0" />
          </div>
          <div className="flex flex-wrap justify-center md:justify-start gap-3">
            {categories.map((cat) => (
              <Link
                key={cat}
                to={`/recipes/?category=${encodeURIComponent(cat)}`}
                className="group flex items-center gap-2 rounded-2xl bg-card-muted border border-card-border px-6 py-3 text-base font-medium capitalize text-content-body transition-all hover:border-brand-border hover:bg-brand-surface hover:text-brand hover:shadow-lg active:scale-95"
              >
                {cat}
              </Link>
            ))}
          </div>
        </section>
      )}

      {/* Featured recipes */}
      <section className="mx-auto max-w-6xl px-4 pb-24">
        <div className="mb-8 flex items-center justify-between border-b border-card-border pb-4">
          <h2 className="font-display text-2xl font-bold text-content md:text-3xl">Latest recipes</h2>
          <Link to="/recipes/" className="group flex items-center gap-1 text-sm font-bold text-brand transition-colors hover:text-brand-hover">
            View all 
            <svg className="h-4 w-4 transition-transform group-hover:translate-x-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
            </svg>
          </Link>
        </div>
        {/* A connectivity failure is already explained by the global
            SiteStatusNotice banner — showing the raw fetch error here too
            would just repeat it in less helpful words. */}
        {error && !isConnectionError && (
          <p className="mb-4 rounded-xl border border-danger-border bg-danger-surface px-4 py-3 text-sm text-danger">{error}</p>
        )}
        <RecipeGrid recipes={featured} loading={loading} emptyMessage="No recipes published yet." />
      </section>
    </div>
  )
}
