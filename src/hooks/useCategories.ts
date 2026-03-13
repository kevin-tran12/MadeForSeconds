import { useEffect, useState } from 'react'
import { getCategories } from '../lib/api'

export function useCategories() {
  const [categories, setCategories] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    async function load() {
      try {
        const data = await getCategories()
        setCategories(data)
      } catch {
        // Silently fail — categories are non-critical
      } finally {
        setLoading(false)
      }
    }

    load()
  }, [])

  return { categories, loading }
}
