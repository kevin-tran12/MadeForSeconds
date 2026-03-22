import { useCallback, useEffect, useRef, useState } from 'react'
import { listPublicRecipes, getGroupedRecipes } from '../lib/api'
import type { Recipe, GroupedRecipes } from '../lib/types'

interface UseRecipesOptions {
  search?: string
  category?: string
  searchBy?: string
}

const PAGE_SIZE = 12

export function useRecipes({ search, category, searchBy }: UseRecipesOptions = {}) {
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [grouped, setGrouped] = useState<GroupedRecipes | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [nextCursor, setNextCursor] = useState<string | null>(null)

  const cursorRef = useRef<string | null>(null)
  const loadingMoreRef = useRef(false)

  const isFiltering = !!(search || category)

  // Load initial data — grouped browse or filtered flat list
  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      setNextCursor(null)
      cursorRef.current = null

      try {
        if (isFiltering) {
          // Flat paginated mode
          setGrouped(null)
          const data = await listPublicRecipes(search, category, searchBy, PAGE_SIZE)
          if (!cancelled) {
            setRecipes(data.recipes)
            setNextCursor(data.next_cursor)
            cursorRef.current = data.next_cursor
          }
        } else {
          // Grouped browse mode
          const data = await getGroupedRecipes()
          if (!cancelled) {
            setGrouped(data)
            setRecipes([])
          }
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load recipes')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  }, [search, category, searchBy])

  // Load more (only in flat/filtered mode)
  const loadMore = useCallback(async () => {
    if (!cursorRef.current || loadingMoreRef.current) return

    loadingMoreRef.current = true
    setLoadingMore(true)
    try {
      const data = await listPublicRecipes(search, category, searchBy, PAGE_SIZE, cursorRef.current)
      setRecipes(prev => [...prev, ...data.recipes])
      setNextCursor(data.next_cursor)
      cursorRef.current = data.next_cursor
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load more recipes')
    } finally {
      loadingMoreRef.current = false
      setLoadingMore(false)
    }
  }, [search, category, searchBy])

  return {
    recipes,
    grouped,
    loading,
    loadingMore,
    error,
    hasMore: !!nextCursor,
    loadMore,
    isFiltering,
  }
}
