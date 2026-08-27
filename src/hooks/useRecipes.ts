import { useCallback, useEffect, useRef, useState } from 'react'
import { listPublicRecipes, getGroupedRecipes } from '../lib/api'
import { isConnectivityError } from '../lib/site-status'
import type { Recipe, GroupedRecipes } from '../lib/types'

interface UseRecipesOptions {
  search?: string
  category?: string
  searchBy?: string
  /** When true, skips grouped browse and fetches a flat list even without filters. */
  forceFlat?: boolean
}

const PAGE_SIZE = 12

export function useRecipes({ search, category, searchBy, forceFlat }: UseRecipesOptions = {}) {
  const [recipes, setRecipes] = useState<Recipe[]>([])
  const [grouped, setGrouped] = useState<GroupedRecipes | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isConnectionError, setIsConnectionError] = useState(false)
  const [nextCursor, setNextCursor] = useState<string | null>(null)

  const cursorRef = useRef<string | null>(null)
  const loadingMoreRef = useRef(false)

  const isFiltering = !!(search || category)
  const useFlatMode = isFiltering || !!forceFlat

  // Load initial data — grouped browse or filtered flat list
  useEffect(() => {
    let cancelled = false

    async function load() {
      setLoading(true)
      setError(null)
      setIsConnectionError(false)
      setNextCursor(null)
      cursorRef.current = null

      try {
        if (useFlatMode) {
          // Flat paginated mode — use larger limit when forced (no-category browse)
          const limit = forceFlat && !isFiltering ? 30 : PAGE_SIZE
          setGrouped(null)
          const data = await listPublicRecipes(search, category, searchBy, limit)
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
        if (!cancelled) {
          setIsConnectionError(isConnectivityError(err))
          setError(err instanceof Error ? err.message : 'Failed to load recipes')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load()
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search, category, searchBy, useFlatMode])

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
      setIsConnectionError(isConnectivityError(err))
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
    isConnectionError,
    hasMore: !!nextCursor,
    loadMore,
    isFiltering,
    isFlat: useFlatMode,
  }
}
