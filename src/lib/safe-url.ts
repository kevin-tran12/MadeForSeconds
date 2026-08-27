/**
 * Return an absolute web URL that is safe to place in an image `src`.
 *
 * Recipe image URLs can come from API data or an admin text field. Restricting
 * them to HTTP(S) prevents executable schemes such as `javascript:` from
 * reaching a DOM URL sink.
 */
export function safeImageUrl(value: string | null | undefined): string | null {
  if (!value) return null

  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}
