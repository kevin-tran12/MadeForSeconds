import { Link } from 'react-router-dom'
import type { Recipe } from '../../lib/types'
import { DifficultyBadge } from './DifficultyBadge'
import { Badge } from '../ui/Badge'

const PLACEHOLDER =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='400' viewBox='0 0 800 400'%3E%3Crect width='800' height='400' fill='%23faedcd'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-size='80' fill='%23e85d04'%3E%F0%9F%8D%BD%EF%B8%8F%3C/text%3E%3C/svg%3E"

export function RecipeDetail({ recipe }: { recipe: Recipe }) {
  const totalMins = recipe.prep_time_minutes + recipe.cook_time_minutes

  return (
    <article className="mx-auto max-w-4xl px-4 py-8">
      {/* Hero image */}
      <div className="mb-8 overflow-hidden rounded-2xl">
        <img
          src={recipe.image_url ?? PLACEHOLDER}
          alt={recipe.title}
          onError={(e) => { e.currentTarget.src = PLACEHOLDER }}
          className="h-72 w-full object-cover md:h-96"
        />
      </div>

      {/* Title & description */}
      <h1 className="font-display text-3xl font-bold text-gray-900 md:text-4xl">{recipe.title}</h1>
      <p className="mt-3 text-gray-600 md:text-lg">{recipe.description}</p>

      {/* Metadata bar */}
      <div className="mt-6 flex flex-wrap items-center gap-4 rounded-xl bg-surface-dark px-5 py-4">
        <MetaItem label="Prep time" value={`${recipe.prep_time_minutes} min`} />
        <div className="hidden h-6 w-px bg-surface-darker sm:block" />
        <MetaItem label="Cook time" value={`${recipe.cook_time_minutes} min`} />
        <div className="hidden h-6 w-px bg-surface-darker sm:block" />
        <MetaItem label="Total time" value={`${totalMins} min`} />
        <div className="hidden h-6 w-px bg-surface-darker sm:block" />
        <MetaItem label="Servings" value={`${recipe.servings}`} />
        <div className="hidden h-6 w-px bg-surface-darker sm:block" />
        <div className="flex flex-col gap-0.5">
          <span className="text-xs font-medium uppercase tracking-wide text-gray-500">Difficulty</span>
          <DifficultyBadge difficulty={recipe.difficulty} />
        </div>
      </div>

      {/* Categories */}
      {recipe.categories.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-2">
          {recipe.categories.map((cat) => (
            <Link key={cat} to={`/recipes?category=${encodeURIComponent(cat)}`}>
              <Badge variant="primary" className="capitalize cursor-pointer hover:opacity-80">{cat}</Badge>
            </Link>
          ))}
        </div>
      )}

      {/* Ingredients + Instructions */}
      <div className="mt-10 grid gap-10 md:grid-cols-3">
        {/* Ingredients */}
        <section>
          <h2 className="font-display text-xl font-bold text-gray-900">Ingredients</h2>
          <ul className="mt-4 space-y-2">
            {recipe.ingredients.map((ing, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-700">
                <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-primary-500" />
                <span>
                  {ing.amount && <strong>{ing.amount} </strong>}
                  {ing.unit && <span className="text-gray-500">{ing.unit} </span>}
                  {ing.item}
                </span>
              </li>
            ))}
          </ul>
        </section>

        {/* Instructions */}
        <section className="md:col-span-2">
          <h2 className="font-display text-xl font-bold text-gray-900">Instructions</h2>
          <ol className="mt-4 space-y-5">
            {recipe.instructions.map((inst) => (
              <li key={inst.step} className="flex gap-4">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary-600 text-sm font-bold text-white">
                  {inst.step}
                </span>
                <p className="pt-0.5 text-sm leading-relaxed text-gray-700">{inst.text}</p>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </article>
  )
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs font-medium uppercase tracking-wide text-gray-500">{label}</span>
      <span className="text-sm font-semibold text-gray-900">{value}</span>
    </div>
  )
}
