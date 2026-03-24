import { useState, useEffect, useCallback } from 'react'
import type { Recipe } from '../../lib/types'
import { RecipeDetail } from '../recipe/RecipeDetail'

interface RecipePreviewPanelProps {
  recipe: Recipe
  isOpen: boolean
  onClose: () => void
  onOpenInTab: () => void
}

export function RecipePreviewPanel({ recipe, isOpen, onClose, onOpenInTab }: RecipePreviewPanelProps) {
  const [rendered, setRendered] = useState(isOpen)
  const [animateIn, setAnimateIn] = useState(false)
  const [panelWidth, setPanelWidth] = useState(() => Math.min(window.innerWidth * 0.5, 900))

  // Mount → animate in; animate out → unmount
  useEffect(() => {
    if (isOpen) {
      setRendered(true)
      // Double rAF ensures the element is painted before the transition starts
      const id = requestAnimationFrame(() => requestAnimationFrame(() => setAnimateIn(true)))
      return () => cancelAnimationFrame(id)
    } else {
      setAnimateIn(false)
      const timer = setTimeout(() => setRendered(false), 360)
      return () => clearTimeout(timer)
    }
  }, [isOpen])

  // Drag-to-resize from the left edge
  const handleDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      const startX = e.clientX
      const startWidth = panelWidth

      const onMouseMove = (e: MouseEvent) => {
        const delta = startX - e.clientX
        const newWidth = Math.min(Math.max(startWidth + delta, 320), window.innerWidth * 0.85)
        setPanelWidth(newWidth)
      }

      const onMouseUp = () => {
        document.removeEventListener('mousemove', onMouseMove)
        document.removeEventListener('mouseup', onMouseUp)
      }

      document.addEventListener('mousemove', onMouseMove)
      document.addEventListener('mouseup', onMouseUp)
    },
    [panelWidth],
  )

  // Escape key closes the panel
  useEffect(() => {
    if (!isOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  if (!rendered) return null

  return (
    <>
      {/* Depth shadow cast to the left — no backdrop so the form stays accessible */}
      <div
        aria-hidden="true"
        className="pointer-events-none fixed inset-0 z-40"
        style={{
          background: 'linear-gradient(to left, rgba(0,0,0,0.18) 0%, transparent 40%)',
          opacity: animateIn ? 1 : 0,
          transition: 'opacity 350ms ease',
        }}
      />

      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Recipe preview"
        className="fixed inset-y-0 right-0 z-50 flex flex-col bg-white"
        style={{
          width: panelWidth,
          boxShadow: '-8px 0 40px rgba(0,0,0,0.18), -1px 0 0 rgba(0,0,0,0.06)',
          transform: animateIn ? 'translateX(0)' : 'translateX(100%)',
          transition: 'transform 350ms cubic-bezier(0.32, 0.72, 0, 1)',
        }}
      >
        {/* Drag handle — left edge */}
        <div
          onMouseDown={handleDragStart}
          title="Drag to resize"
          className="absolute inset-y-0 left-0 z-10 w-2 cursor-col-resize"
        >
          <div className="absolute inset-y-0 left-0 w-px bg-gray-200 transition-colors hover:bg-primary-400" />
          {/* Wider invisible hit area */}
        </div>

        {/* Header */}
        <div className="flex shrink-0 items-center justify-between border-b border-gray-200 bg-gray-50/80 px-4 py-2.5 pl-4 backdrop-blur-sm">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-widest text-gray-400">Preview</span>
            {!recipe.published && (
              <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-700">
                Draft
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={onOpenInTab}
              className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-gray-500 transition-colors hover:bg-gray-200 hover:text-gray-800"
              title="Open in new tab"
            >
              {/* External link icon */}
              <svg width="11" height="11" viewBox="0 0 11 11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M6.5 1H10v3.5M10 1L5.5 5.5M4.5 2H2a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h6a1 1 0 0 0 1-1V7" />
              </svg>
              New tab
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-gray-400 transition-colors hover:bg-gray-200 hover:text-gray-700"
              aria-label="Close preview"
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M1 1l12 12M13 1L1 13" />
              </svg>
            </button>
          </div>
        </div>

        {/* Scrollable recipe content */}
        <div className="flex-1 overflow-y-auto">
          <RecipeDetail recipe={recipe} />
        </div>
      </div>
    </>
  )
}
