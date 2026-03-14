import { useEffect } from 'react'

interface PageMeta {
  title?: string
  description?: string
  image?: string | null
  url?: string
  type?: 'website' | 'article'
}

const DEFAULT_TITLE = 'MadeForSeconds'
const DEFAULT_DESCRIPTION =
  'The kitchen\'s a mess. The food\'s good.'
const SITE_URL = 'https://madeforseconds.com'

function setMeta(name: string, content: string, property = false) {
  const attr = property ? 'property' : 'name'
  let el = document.querySelector<HTMLMetaElement>(`meta[${attr}="${name}"]`)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, name)
    document.head.appendChild(el)
  }
  el.setAttribute('content', content)
}

export function usePageMeta({ title, description, image, url, type = 'website' }: PageMeta) {
  useEffect(() => {
    const fullTitle = title ? `${title} — MadeForSeconds` : DEFAULT_TITLE
    const desc = description ?? DEFAULT_DESCRIPTION
    const pageUrl = url ?? SITE_URL

    document.title = fullTitle

    setMeta('description', desc)

    // Open Graph
    setMeta('og:type', type, true)
    setMeta('og:site_name', 'MadeForSeconds', true)
    setMeta('og:title', fullTitle, true)
    setMeta('og:description', desc, true)
    setMeta('og:url', pageUrl, true)
    if (image) setMeta('og:image', image, true)

    // Twitter Card
    setMeta('twitter:card', image ? 'summary_large_image' : 'summary')
    setMeta('twitter:title', fullTitle)
    setMeta('twitter:description', desc)
    if (image) setMeta('twitter:image', image)

    return () => {
      document.title = DEFAULT_TITLE
    }
  }, [title, description, image, url, type])
}
