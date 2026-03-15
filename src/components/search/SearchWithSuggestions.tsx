import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSearchSuggestions } from '../../hooks/useSearchSuggestions'
import type { Recipe } from '../../lib/types'

const PLACEHOLDER =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='64' height='64' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' fill='%23faedcd'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-size='28' fill='%23e85d04'%3E%F0%9F%8D%BD%EF%B8%8F%3C/text%3E%3C/svg%3E"

const SEARCH_BY_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'name', label: 'Name' },
  { value: 'ingredient', label: 'Ingredient' },
]

interface SearchWithSuggestionsProps {
  initialQuery?: string
  initialSearchBy?: string
  inputClassName?: string
  onClose?: () => void
}

export function SearchWithSuggestions({
  initialQuery = '',
  initialSearchBy = 'all',
  inputClassName,
  onClose,
}: SearchWithSuggestionsProps) {
  const navigate = useNavigate()
  const [query, setQuery] = useState(initialQuery)
  const [searchBy, setSearchBy] = useState(initialSearchBy)
  const [activeIndex, setActiveIndex] = useState(-1)
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const { suggestions } = useSearchSuggestions(query, searchBy)

  // Show dropdown when there are suggestions
  useEffect(() => {
    setOpen(suggestions.length > 0 && query.length >= 2)
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
        goToRecipe(suggestions[activeIndex])
      }
    }
  }

  return (
    <div ref={containerRef} className="relative flex flex-col gap-2 w-full">
      {/* Input row */}
      <div className={`flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-1.5 shadow-sm ring-2 ring-primary-100 focus-within:ring-primary-300 ${inputClassName ?? ''}`}>
        <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
        </svg>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          onFocus={() => suggestions.length > 0 && query.length >= 2 && setOpen(true)}
          placeholder="Search recipes…"
          className="flex-1 bg-transparent text-sm text-gray-900 placeholder-gray-400 outline-none min-w-0"
        />
        {query && (
          <button
            type="button"
            onClick={() => { setQuery(''); setOpen(false) }}
            className="text-gray-400 hover:text-gray-600"
            aria-label="Clear"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
        <button
          type="button"
          onClick={submit}
          className="shrink-0 rounded-lg bg-primary-500 px-3 py-1 text-sm font-semibold text-white hover:bg-primary-400 active:scale-95 transition-all"
        >
          Go
        </button>
      </div>

      {/* Search-by toggle */}
      <div className="flex gap-1">
        {SEARCH_BY_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => setSearchBy(opt.value)}
            className={`rounded-full px-3 py-0.5 text-xs font-medium transition-colors ${
              searchBy === opt.value
                ? 'bg-primary-500 text-white'
                : 'bg-gray-100 text-gray-500 hover:bg-gray-200'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Dropdown */}
      {open && (
        <div className="absolute top-full left-0 right-0 z-50 mt-1 overflow-hidden rounded-xl border border-gray-100 bg-white shadow-lg">
          {suggestions.map((recipe, i) => (
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
                className="h-8 w-8 shrink-0 rounded-md object-cover"
              />
              <span className="truncate text-sm font-medium text-gray-900">{recipe.title}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
