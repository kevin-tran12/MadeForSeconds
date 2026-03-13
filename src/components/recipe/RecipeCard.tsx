import { Link } from 'react-router-dom'
import type { Recipe } from '../../lib/types'
import { DifficultyBadge } from './DifficultyBadge'
import { Badge } from '../ui/Badge'

const PLACEHOLDER =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='400' height='300' viewBox='0 0 400 300'%3E%3Crect width='400' height='300' fill='%23faedcd'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-size='48' fill='%23e85d04'%3E%F0%9F%8D%BD%EF%B8%8F%3C/text%3E%3C/svg%3E"

interface RecipeCardProps {
  recipe: Recipe
}

export function RecipeCard({ recipe }: RecipeCardProps) {
  const totalMins = recipe.prep_time_minutes + recipe.cook_time_minutes

  return (
    <Link
      to={`/recipes/${recipe.slug}`}
      className="group flex flex-col overflow-hidden rounded-xl border border-surface-darker bg-white shadow-sm transition-all hover:-translate-y-1 hover:shadow-md"
    >
      {/* Image */}
      <div className="aspect-[4/3] overflow-hidden bg-surface-dark">
        <img
          src={recipe.image_url ?? PLACEHOLDER}
          alt={recipe.title}
          onError={(e) => { e.currentTarget.src = PLACEHOLDER }}
          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
        />
      </div>

      {/* Content */}
      <div className="flex flex-1 flex-col gap-2 p-4">
        <h3 className="font-display text-lg font-semibold text-gray-900 line-clamp-2 leading-snug">
          {recipe.title}
        </h3>
        <p className="text-sm text-gray-600 line-clamp-2 flex-1">{recipe.description}</p>

        {/* Meta row */}
        <div className="flex items-center gap-3 text-xs text-gray-500">
          <span className="flex items-center gap-1">
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {totalMins} min
          </span>
          <span className="flex items-center gap-1">
            <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0" />
            </svg>
            {recipe.servings}
          </span>
          <DifficultyBadge difficulty={recipe.difficulty} />
        </div>

        {/* Categories */}
        {recipe.categories.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {recipe.categories.slice(0, 3).map((cat) => (
              <Badge key={cat} className="capitalize">{cat}</Badge>
            ))}
          </div>
        )}
      </div>
    </Link>
  )
}
