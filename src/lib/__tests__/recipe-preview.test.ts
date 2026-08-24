import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Recipe } from '../types'
import { openRecipeDraftPreview, waitForRecipeDraftPreview } from '../recipe-preview'

const recipe: Recipe = {
  id: 'preview-draft',
  slug: 'preview-draft',
  title: 'Draft recipe',
  description: '',
  ingredients: [],
  instructions: [],
  prep_time_minutes: 0,
  cook_time_minutes: 0,
  servings: 1,
  difficulty: 'easy',
  categories: [],
  image_url: null,
  published: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  nutrition: [],
  secrets: [{ title: 'Use high heat', body: 'Keep the pan hot.' }],
}

const originalOpener = window.opener

afterEach(() => {
  vi.restoreAllMocks()
  Object.defineProperty(window, 'opener', { configurable: true, value: originalOpener })
})

describe('recipe draft preview transfer', () => {
  it('sends the draft to the same-origin preview window without browser storage', () => {
    const previewWindow = {
      focus: vi.fn(),
      postMessage: vi.fn(),
    } as unknown as Window
    vi.spyOn(window, 'open').mockReturnValue(previewWindow)
    const storageSpy = vi.spyOn(Storage.prototype, 'setItem')

    expect(openRecipeDraftPreview(recipe)).toBe(previewWindow)
    window.dispatchEvent(new MessageEvent('message', {
      origin: window.location.origin,
      source: previewWindow,
      data: { type: 'mfs:recipe-preview-ready' },
    }))

    expect(previewWindow.postMessage).toHaveBeenCalledWith(
      { type: 'mfs:recipe-preview-data', recipe },
      window.location.origin,
    )
    expect(storageSpy).not.toHaveBeenCalled()
  })

  it('accepts preview data only from the same-origin opener', () => {
    const opener = { postMessage: vi.fn() } as unknown as Window
    Object.defineProperty(window, 'opener', { configurable: true, value: opener })
    const onRecipe = vi.fn()
    const onError = vi.fn()
    const cleanup = waitForRecipeDraftPreview(onRecipe, onError)

    expect(opener.postMessage).toHaveBeenCalledWith(
      { type: 'mfs:recipe-preview-ready' },
      window.location.origin,
    )
    window.dispatchEvent(new MessageEvent('message', {
      origin: 'https://attacker.example',
      source: opener,
      data: { type: 'mfs:recipe-preview-data', recipe },
    }))
    expect(onRecipe).not.toHaveBeenCalled()

    window.dispatchEvent(new MessageEvent('message', {
      origin: window.location.origin,
      source: opener,
      data: { type: 'mfs:recipe-preview-data', recipe },
    }))
    expect(onRecipe).toHaveBeenCalledWith(recipe)
    expect(onError).not.toHaveBeenCalled()
    cleanup()
  })
})
