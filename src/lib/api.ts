import { apiFetch } from './api-client'
import type { Recipe, RecipeFormData } from './types'

// ─── Public endpoints ───────────────────────────────────────────────────────

export async function listPublicRecipes(search?: string, category?: string): Promise<Recipe[]> {
  const params = new URLSearchParams()
  if (search) params.set('search', search)
  if (category) params.set('category', category)
  const qs = params.toString()
  return apiFetch<Recipe[]>(`/api/recipes${qs ? `?${qs}` : ''}`)
}

export async function getRecipe(slug: string): Promise<Recipe> {
  return apiFetch<Recipe>(`/api/recipes/${encodeURIComponent(slug)}`)
}

export async function getCategories(): Promise<string[]> {
  return apiFetch<string[]>('/api/categories')
}

// ─── Admin endpoints ────────────────────────────────────────────────────────

export const adminApi = {
  listRecipes: (): Promise<Recipe[]> => apiFetch('/api/admin/recipes'),

  createRecipe: (data: RecipeFormData): Promise<Recipe> =>
    apiFetch('/api/admin/recipes', { method: 'POST', body: JSON.stringify(data) }),

  updateRecipe: (id: string, data: Partial<RecipeFormData>): Promise<Recipe> =>
    apiFetch(`/api/admin/recipes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteRecipe: (id: string): Promise<void> =>
    apiFetch(`/api/admin/recipes/${id}`, { method: 'DELETE' }),
}
