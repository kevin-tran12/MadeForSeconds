import { useState, useEffect, useCallback } from 'react'
import type { Recipe } from '../../lib/types'

interface CookingModeProps {
  recipe: Recipe
  onExit: () => void
}

export function CookingMode({ recipe, onExit }: CookingModeProps) {
  const [currentStep, setCurrentStep] = useState(0)
  const [showIngredients, setShowIngredients] = useState(false)
  const total = recipe.instructions.length

  // Keep screen awake while cooking
  useEffect(() => {
    let wakeLock: WakeLockSentinel | null = null
    if ('wakeLock' in navigator) {
      navigator.wakeLock.request('screen').then((lock) => {
        wakeLock = lock
      }).catch(() => {/* ignore if denied */})
    }
    return () => {
      wakeLock?.release()
    }
  }, [])

  // Keyboard navigation
  const prev = useCallback(() => setCurrentStep((s) => Math.max(0, s - 1)), [])
  const next = useCallback(() => setCurrentStep((s) => Math.min(total - 1, s + 1)), [total])

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === 'ArrowRight') next()
      if (e.key === 'ArrowLeft') prev()
      if (e.key === 'Escape') onExit()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [next, prev, onExit])

  const step = recipe.instructions[currentStep]
  const progress = ((currentStep + 1) / total) * 100

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-gray-950 text-white">
      {/* Top bar */}
      <div className="flex items-center justify-between border-b border-white/10 px-6 py-4">
        <span className="truncate text-sm font-medium text-white/60 max-w-xs md:max-w-md">
          {recipe.title}
        </span>
        <span className="shrink-0 text-sm font-bold text-white/80">
          Step {currentStep + 1} of {total}
        </span>
        <button
          onClick={onExit}
          className="ml-4 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20"
          aria-label="Exit cooking mode"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Progress bar */}
      <div className="h-1 w-full bg-white/10">
        <div
          className="h-full bg-primary-500 transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Step content */}
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-8 md:px-16">
        <p className="max-w-2xl text-center text-2xl font-medium leading-relaxed text-white md:text-4xl md:leading-relaxed">
          {step.text}
        </p>
      </div>

      {/* Bottom controls */}
      <div className="border-t border-white/10 px-6 py-6">
        {/* Nav buttons */}
        <div className="flex gap-4">
          <button
            onClick={prev}
            disabled={currentStep === 0}
            className="flex flex-1 items-center justify-center gap-2 rounded-2xl bg-white/10 py-4 text-base font-semibold transition-colors hover:bg-white/20 disabled:opacity-30 disabled:cursor-not-allowed"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            Previous
          </button>
          {currentStep < total - 1 ? (
            <button
              onClick={next}
              className="flex flex-1 items-center justify-center gap-2 rounded-2xl bg-primary-600 py-4 text-base font-semibold transition-colors hover:bg-primary-500"
            >
              Next
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
              </svg>
            </button>
          ) : (
            <button
              onClick={onExit}
              className="flex flex-1 items-center justify-center gap-2 rounded-2xl bg-green-600 py-4 text-base font-semibold transition-colors hover:bg-green-500"
            >
              Done! 🎉
            </button>
          )}
        </div>

        {/* Ingredients toggle */}
        <button
          onClick={() => setShowIngredients((v) => !v)}
          className="mt-4 w-full rounded-xl bg-white/5 py-3 text-sm font-medium text-white/60 transition-colors hover:bg-white/10 hover:text-white"
        >
          {showIngredients ? 'Hide' : 'Show'} ingredients
        </button>

        {/* Ingredients panel */}
        {showIngredients && (
          <div className="mt-4 max-h-48 overflow-y-auto rounded-2xl bg-white/5 p-4">
            <ul className="space-y-2">
              {recipe.ingredients.map((ing, i) => (
                <li key={i} className="flex items-baseline gap-2 text-sm text-white/80">
                  <span className="h-1 w-1 shrink-0 rounded-full bg-primary-400 mt-2" />
                  <span>
                    {ing.amount && <strong className="text-white">{ing.amount} </strong>}
                    {ing.unit && <span className="text-white/60">{ing.unit} </span>}
                    {ing.item}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
