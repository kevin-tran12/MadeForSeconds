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
    <div className="flex flex-col gap-2">
      <div className="relative">
        <svg
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
          />
        </svg>
        <input
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Search recipes..."
          className="w-full rounded-lg border border-gray-300 bg-white py-2 pl-9 pr-4 text-sm outline-none transition-colors focus:border-primary-500 focus:ring-2 focus:ring-primary-100"
        />
        {value && (
          <button
            onClick={() => onChange('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            aria-label="Clear search"
          >
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      <div className="flex gap-1.5">
        {SEARCH_BY_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onSearchByChange(opt.value)}
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
    </div>
  )
}
