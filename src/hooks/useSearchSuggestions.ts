import { useEffect, useRef, useState } from 'react'
import { listPublicRecipes } from '../lib/api'
import type { Recipe } from '../lib/types'

export function useSearchSuggestions(query: string, searchBy: string) {
  const [suggestions, setSuggestions] = useState<Recipe[]>([])
  const [loading, setLoading] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (query.length < 2) {
      setSuggestions([])
      setLoading(false)
      return
    }

    if (debounceRef.current) clearTimeout(debounceRef.current)

    debounceRef.current = setTimeout(async () => {
      if (abortRef.current) abortRef.current.abort()
      abortRef.current = new AbortController()

      setLoading(true)
      try {
        const results = await listPublicRecipes(query, undefined, searchBy)
        setSuggestions(results.slice(0, 6))
      } catch {
        // Ignore aborted requests
      } finally {
        setLoading(false)
      }
    }, 300)

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [query, searchBy])

  return { suggestions, loading }
}
