import { useEffect, useMemo, useState } from 'react'
import { listPublicRecipes } from '../lib/api'
import type { Recipe } from '../lib/types'

// Module-level cache — fetched once, shared across every search instance.
let cachedRecipes: Recipe[] | null = null
let fetchPromise: Promise<Recipe[]> | null = null

function getAllRecipes(): Promise<Recipe[]> {
  if (cachedRecipes) return Promise.resolve(cachedRecipes)
  if (!fetchPromise) {
    fetchPromise = listPublicRecipes(undefined, undefined, undefined, 50).then((data) => {
      cachedRecipes = data.recipes
      return data.recipes
    })
  }
  return fetchPromise
}

export interface SuggestionResult {
  recipe: Recipe
  /** Ingredient names that matched the query (empty if only title matched) */
  matchedIngredients: string[]
}

export function useSearchSuggestions(query: string, searchBy: string) {
  const [allRecipes, setAllRecipes] = useState<Recipe[]>(cachedRecipes ?? [])
  const [loading, setLoading] = useState(!cachedRecipes)

  useEffect(() => {
    if (cachedRecipes) {
      setAllRecipes(cachedRecipes)
      setLoading(false)
      return
    }
    setLoading(true)
    getAllRecipes()
      .then(setAllRecipes)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  // Filter client-side on every keystroke — instant, zero extra network calls
  const suggestions = useMemo((): SuggestionResult[] => {
    const q = query.trim().toLowerCase()
    if (!q) return []

    // An ingredient matches only if at least one word in its name STARTS WITH
    // the query — prevents mid-word hits like "sli[c]ed" or "ne[c]k".
    function ingredientMatches(item: string): boolean {
      return item.toLowerCase().split(/[\s,]+/).some((word) => word.startsWith(q))
    }

    const results: SuggestionResult[] = []

    for (const recipe of allRecipes) {
      const matchesName =
        (searchBy === 'all' || searchBy === 'name') &&
        recipe.title.toLowerCase().includes(q)

      const matchedIngredients =
        searchBy === 'all' || searchBy === 'ingredient'
          ? recipe.ingredients
              .filter((ing) => ingredientMatches(ing.item))
              .map((ing) => ing.item)
          : []

      if (matchesName || matchedIngredients.length > 0) {
        // Only surface ingredient matches when the title didn't already match,
        // so the label isn't redundant on a name hit.
        results.push({
          recipe,
          matchedIngredients: matchesName ? [] : matchedIngredients,
        })
      }

      if (results.length === 6) break
    }

    return results
  }, [query, searchBy, allRecipes])

  return { suggestions, loading }
}
