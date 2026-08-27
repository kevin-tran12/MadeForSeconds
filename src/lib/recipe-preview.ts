import type { Recipe } from './types'

const PREVIEW_READY = 'mfs:recipe-preview-ready'
const PREVIEW_DATA = 'mfs:recipe-preview-data'
const PREVIEW_TIMEOUT_MS = 10_000

interface PreviewDataMessage {
  type: typeof PREVIEW_DATA
  recipe: Recipe
}

function isPreviewDataMessage(value: unknown): value is PreviewDataMessage {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Partial<PreviewDataMessage>
  return candidate.type === PREVIEW_DATA && typeof candidate.recipe === 'object' && candidate.recipe !== null
}

/** Send an unsaved recipe directly to a same-origin preview tab without persistence. */
export function openRecipeDraftPreview(recipe: Recipe): Window | null {
  let previewWindow: Window | null = null
  let timeoutId: number | null = null

  const cleanup = () => {
    window.removeEventListener('message', handleReady)
    if (timeoutId !== null) window.clearTimeout(timeoutId)
  }

  const handleReady = (event: MessageEvent) => {
    if (
      previewWindow === null ||
      event.origin !== window.location.origin ||
      event.source !== previewWindow ||
      event.data?.type !== PREVIEW_READY
    ) {
      return
    }

    previewWindow.postMessage({ type: PREVIEW_DATA, recipe }, window.location.origin)
    cleanup()
  }

  window.addEventListener('message', handleReady)
  previewWindow = window.open('/admin/preview/draft/', '_blank')
  if (!previewWindow) {
    cleanup()
    return null
  }

  timeoutId = window.setTimeout(cleanup, PREVIEW_TIMEOUT_MS)
  previewWindow.focus()
  return previewWindow
}

/** Receive an unsaved recipe from the same-origin admin tab that opened this tab. */
export function waitForRecipeDraftPreview(
  onRecipe: (recipe: Recipe) => void,
  onError: (message: string) => void,
): () => void {
  const opener = window.opener
  if (!opener) {
    onError('Preview data not found. Go back and click Preview again.')
    return () => undefined
  }

  let timeoutId: number | null = null
  const cleanup = () => {
    window.removeEventListener('message', handleData)
    if (timeoutId !== null) window.clearTimeout(timeoutId)
  }

  const handleData = (event: MessageEvent) => {
    if (
      event.origin !== window.location.origin ||
      event.source !== opener ||
      !isPreviewDataMessage(event.data)
    ) {
      return
    }

    cleanup()
    onRecipe(event.data.recipe)
  }

  window.addEventListener('message', handleData)
  timeoutId = window.setTimeout(() => {
    cleanup()
    onError('Preview data not found. Go back and click Preview again.')
  }, PREVIEW_TIMEOUT_MS)
  opener.postMessage({ type: PREVIEW_READY }, window.location.origin)

  return cleanup
}
