import { describe, expect, it } from 'vitest'
import { safeImageUrl } from '../safe-url'

describe('safeImageUrl', () => {
  it.each([
    'https://images.example.com/recipe.jpg',
    'http://localhost:8000/image.png',
  ])('allows HTTP(S) image URLs: %s', (value) => {
    expect(safeImageUrl(value)).toBe(value)
  })

  it.each([
    'javascript:alert(1)',
    'data:image/svg+xml,<svg onload=alert(1)>',
    'file:///etc/passwd',
    '/relative/image.jpg',
    'not a url',
    '',
  ])('rejects non-web or malformed URLs: %s', (value) => {
    expect(safeImageUrl(value)).toBeNull()
  })
})
