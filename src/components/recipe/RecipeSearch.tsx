const SEARCH_BY_OPTIONS = [
  { value: 'all', label: 'All' },
  { value: 'name', label: 'Name' },
  { value: 'ingredient', label: 'Ingredient' },
]

interface RecipeSearchProps {
  value: string
  onChange: (value: string) => void
  searchBy: string
  onSearchByChange: (searchBy: string) => void
}

export function RecipeSearch({ value, onChange, searchBy, onSearchByChange }: RecipeSearchProps) {
  return (
    <div className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-1.5 shadow-sm ring-2 ring-primary-100 focus-within:ring-primary-300 transition-shadow">
      {/* Search icon */}
      <svg className="h-4 w-4 shrink-0 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 1 1 5 11a6 6 0 0 1 12 0z" />
      </svg>

      {/* Inline search-by dropdown */}
      <div className="relative flex items-center border-r border-gray-200 pr-5 mr-0.5 shrink-0">
        <select
          value={searchBy}
          onChange={(e) => onSearchByChange(e.target.value)}
          className="appearance-none bg-transparent text-xs font-semibold text-gray-500 outline-none cursor-pointer"
          aria-label="Search by"
        >
          {SEARCH_BY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
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
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Search recipes…"
        className="flex-1 bg-transparent text-sm text-gray-900 placeholder-gray-400 outline-none min-w-0"
      />

      {/* Clear button */}
      {value && (
        <button
          type="button"
          onClick={() => onChange('')}
          className="text-gray-400 hover:text-gray-600 transition-colors"
          aria-label="Clear search"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      )}
    </div>
  )
}
