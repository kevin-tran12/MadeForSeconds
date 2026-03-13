import { useEffect, useState } from 'react'
import { getRecipe } from '../lib/api'
import type { Recipe } from '../lib/types'

export function useRecipe(slug: string | undefined) {
  const [recipe, setRecipe] = useState<Recipe | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!slug) {
      setLoading(false)
      return
    }

    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)

      try {
        const data = await getRecipe(slug!)
        if (!cancelled) setRecipe(data)
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Recipe not found')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [slug])

  return { recipe, loading, error }
}
