import { useState, useEffect } from 'react'
import { getPageContent } from '../lib/api'

/**
 * Fetches page content from /api/pages/{pageId}.
 * Falls back to `defaults` for any missing key or on fetch error.
 */
export function usePageContent(
  pageId: string,
  defaults: Record<string, string>,
): Record<string, string> {
  const [content, setContent] = useState<Record<string, string>>(defaults)

  useEffect(() => {
    getPageContent(pageId)
      .then((data) => {
        // Merge: use fetched value when present, fall back to default
        const merged: Record<string, string> = { ...defaults }
        for (const key of Object.keys(defaults)) {
          if (data[key] !== undefined && data[key] !== '') {
            merged[key] = data[key]
          }
        }
        setContent(merged)
      })
      .catch(() => {
        // Keep defaults on error
      })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageId])

  return content
}
