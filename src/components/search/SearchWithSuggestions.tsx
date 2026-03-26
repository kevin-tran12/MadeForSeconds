import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSearchSuggestions } from '../../hooks/useSearchSuggestions'
import type { Recipe } from '../../lib/types'

const PLACEHOLDER =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='64' height='64' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' fill='%23faedcd'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-size='28' fill='%23e85d04'%3E%F0%9F%8D%BD%EF%B8%8F%3C/text%3E%3C/svg%3E"

interface SearchWithSuggestionsProps {
  initialQuery?: string
  initialSearchBy?: string
  inputClassName?: string
  autoFocus?: boolean
  onClose?: () => void
}

export function SearchWithSuggestions({
  initialQuery = '',
  initialSearchBy = 'all',
  inputClassName,
  autoFocus,
  onClose,
}: SearchWithSuggestionsProps) {
  const navigate = useNavigate()
  const [query, setQuery] = useState(initialQuery)
  const [searchBy, setSearchBy] = useState(initialSearchBy)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const { suggestions, loading } = useSearchSuggestions(query, searchBy)

  // Auto-focus when opened from header
  useEffect(() => {
    if (autoFocus) {
      const t = setTimeout(() => inputRef.current?.focus(), 50)
      return () => clearTimeout(t)
    }
  }, [autoFocus])

  // Show dropdown when there are suggestions (1+ chars, client-side so instant)
  useEffect(() => {
    setOpen(suggestions.length > 0 && query.trim().length >= 1)
    setActiveIndex(-1)
  }, [suggestions, query])

  // Close on outside click
  useEffect(() => {
    function handle(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handle)
    return () => document.removeEventListener('mousedown', handle)
  }, [])

  function goToRecipe(recipe: Recipe) {
    setOpen(false)
    setQuery('')
    onClose?.()
    navigate(`/recipes/${recipe.slug}`)
  }

  function submit() {
    const q = query.trim()
    setOpen(false)
    onClose?.()
    if (q) {
      const params = new URLSearchParams()
      params.set('q', q)
      if (searchBy !== 'all') params.set('search_by', searchBy)
      navigate(`/recipes?${params.toString()}`)
    } else {
      navigate('/recipes')
    }
  }

  // onKeyDownCapture fires in the capture phase — before the <select> can
  // consume arrow keys natively — so suggestions always take priority.
  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') {
      setOpen(false)
      onClose?.()
      return
    }
    if (!open) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex((i) => Math.min(i + 1, suggestions.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex((i) => Math.max(i - 1, -1))
    } else if (e.key === 'Enter') {
      if (activeIndex >= 0 && suggestions[activeIndex]) {
        e.preventDefault()
        goToRecipe(suggestions[activeIndex].recipe)
      }
    }
  }

  return (
    <div
      ref={containerRef}
      className="relative w-full"
      onKeyDownCapture={handleKeyDown}
      onClick={() => inputRef.current?.focus()}
    >
      {/* Input row with inline search-by dropdown */}
      <div
        className={`flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-1.5 shadow-sm ring-2 ring-primary-100 focus-within:ring-primary-300 transition-shadow ${inputClassName ?? ''}`}
      >
        {/* Search icon / loading spinner */}
        {loading ? (
          <svg className="h-4 w-4 shrink-0 animate-spin text-primary-400" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
          </svg>
        ) : (
          <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
          </svg>
        )}

        {/* Search-by dropdown — inline inside the bar */}
        <div className="relative flex items-center border-r border-gray-200 pr-5 mr-0.5 shrink-0">
          <select
            value={searchBy}
            onChange={(e) => setSearchBy(e.target.value)}
            onClick={(e) => e.stopPropagation()}
            className="appearance-none bg-transparent text-xs font-semibold text-gray-500 outline-none cursor-pointer"
            aria-label="Search by"
          >
            <option value="all">All</option>
            <option value="name">Name</option>
            <option value="ingredient">Ingredient</option>
            <option value="label">Label</option>
          </select>
          {/* Chevron icon */}
          <svg
            className="pointer-events-none absolute right-1 top-1/2 -translate-y-1/2 h-3 w-3 text-gray-400"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
              clipRule="evenodd"
            />
          </svg>
        </div>

        {/* Text input */}
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => suggestions.length > 0 && query.trim().length >= 1 && setOpen(true)}
          placeholder="Search recipes…"
          className="flex-1 bg-transparent text-sm text-gray-900 placeholder-gray-400 outline-none min-w-0"
        />

        {/* Clear button */}
        {query && (
          <button
            type="button"
            onClick={() => { setQuery(''); setOpen(false) }}
            className="text-gray-400 hover:text-gray-600 transition-colors"
            aria-label="Clear"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}

        {/* Go button */}
        <button
          type="button"
          onClick={submit}
          className="shrink-0 rounded-lg bg-primary-500 px-3 py-1 text-sm font-semibold text-white hover:bg-primary-400 active:scale-95 transition-all"
        >
          Go
        </button>
      </div>

      {/* Suggestions dropdown */}
      {open && (
        <div className="absolute top-full left-0 right-0 z-50 mt-1 overflow-hidden rounded-xl border border-gray-100 bg-white shadow-lg animate-dropdown-in">
          {suggestions.map(({ recipe, matchedIngredients }, i) => (
            <button
              key={recipe.id}
              type="button"
              onClick={() => goToRecipe(recipe)}
              className={`flex w-full items-center gap-3 px-3 py-2 text-left transition-colors ${
                i === activeIndex ? 'bg-primary-50' : 'hover:bg-gray-50'
              }`}
            >
              <img
                src={recipe.image_url ?? PLACEHOLDER}
                alt={recipe.title}
                onError={(e) => { e.currentTarget.src = PLACEHOLDER }}
                className="h-9 w-9 shrink-0 rounded-md object-cover"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-gray-900">{recipe.title}</p>
                {matchedIngredients.length > 0 && (
                  <p className="truncate text-xs text-primary-500 mt-0.5">
                    Contains: {matchedIngredients.slice(0, 3).join(', ')}
                    {matchedIngredients.length > 3 && ` +${matchedIngredients.length - 3} more`}
                  </p>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
