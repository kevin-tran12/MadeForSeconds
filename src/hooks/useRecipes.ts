import { useEffect, useState } from 'react'
import { listPublicRecipes } from '../lib/api'
import type { Recipe } from '../lib/types'

interface UseRecipesOptions {
  search?: string
  category?: string
}

export function useRecipes({ search, category }: UseRecipesOptions = {}) {
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)

      try {
        const data = await listPublicRecipes(search, category)
        if (!cancelled) setRecipes(data)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load recipes')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [search, category])

  return { recipes, loading, error }
}
