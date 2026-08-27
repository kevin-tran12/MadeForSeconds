import type { Recipe } from '../../lib/types'
import { DifficultyBadge } from '../recipe/DifficultyBadge'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { EmptyState } from '../ui/EmptyState'
import { safeImageUrl } from '../../lib/safe-url'

const PLACEHOLDER =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='60' height='60' viewBox='0 0 60 60'%3E%3Crect width='60' height='60' fill='%23faedcd'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-size='28' fill='%23e85d04'%3E%F0%9F%8D%BD%EF%B8%8F%3C/text%3E%3C/svg%3E"

interface RecipeTableProps {
  recipes: Recipe[]
  loading: boolean
  onEdit: (id: string) => void
  onDelete: (id: string) => Promise<void>
  onTogglePublish: (recipe: Recipe) => Promise<void>
  onPreview: (recipe: Recipe) => void
}

export function RecipeTable({ recipes, loading, onEdit, onDelete, onTogglePublish, onPreview }: RecipeTableProps) {
  if (loading) return <LoadingSpinner size="lg" className="py-16" />
  if (recipes.length === 0) {
    return <EmptyState title="No recipes yet" message="Create your first recipe to get started." />
  }

  async function handleDelete(recipe: Recipe) {
    if (!confirm(`Delete "${recipe.title}"? This cannot be undone.`)) return
    await onDelete(recipe.id)
  }

  return (
    <div className="overflow-x-auto rounded-xl border border-surface-darker bg-white">
      <table className="w-full text-sm">
        <thead className="border-b border-surface-darker bg-surface text-left">
          <tr>
            <th className="px-4 py-3 font-medium text-gray-600">Recipe</th>
            <th className="px-4 py-3 font-medium text-gray-600">Difficulty</th>
            <th className="px-4 py-3 font-medium text-gray-600">Status</th>
            <th className="px-4 py-3 font-medium text-gray-600">Time</th>
            <th className="px-4 py-3 font-medium text-gray-600 text-right">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-darker">
          {recipes.map((recipe) => (
            <tr key={recipe.id} className="hover:bg-surface/50">
              {/* Recipe */}
              <td className="px-4 py-3">
                <div className="flex items-center gap-3">
                  <img
                    src={safeImageUrl(recipe.image_url) ?? PLACEHOLDER}
                    alt={recipe.title}
                    onError={(e) => { e.currentTarget.src = PLACEHOLDER }}
                    className="h-10 w-10 shrink-0 rounded-lg object-cover"
                  />
                  <span className="font-medium text-gray-900 line-clamp-1">{recipe.title}</span>
                </div>
              </td>
              {/* Difficulty */}
              <td className="px-4 py-3">
                <DifficultyBadge difficulty={recipe.difficulty} />
              </td>
              {/* Status */}
              <td className="px-4 py-3">
                <Badge variant={recipe.published ? 'success' : 'default'}>
                  {recipe.published ? 'Published' : 'Draft'}
                </Badge>
              </td>
              {/* Time */}
              <td className="px-4 py-3 text-gray-500">
                {recipe.prep_time_minutes + recipe.cook_time_minutes} min
              </td>
              {/* Actions */}
              <td className="px-4 py-3">
                <div className="flex items-center justify-end gap-2">
                  <Button variant="ghost" size="sm" onClick={() => onTogglePublish(recipe)}>
                    {recipe.published ? 'Unpublish' : 'Publish'}
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => onPreview(recipe)}>
                    Preview
                  </Button>
                  <Button variant="secondary" size="sm" onClick={() => onEdit(recipe.id)}>
                    Edit
                  </Button>
                  <Button variant="danger" size="sm" onClick={() => handleDelete(recipe)}>
                    Delete
                  </Button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
