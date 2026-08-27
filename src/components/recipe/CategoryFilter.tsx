interface CategoryFilterProps {
  categories: string[]
  selected: string | null
  onSelect: (category: string | null) => void
}

export function CategoryFilter({ categories, selected, onSelect }: CategoryFilterProps) {
  if (categories.length === 0) return null

  return (
    <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-thin">
      <button
        onClick={() => onSelect(null)}
        className={[
          'shrink-0 rounded-full px-4 py-1.5 text-sm font-medium transition-colors',
          selected === null
            ? 'bg-primary-600 text-on-brand'
            : 'border border-card-border bg-card-muted text-content-body hover:border-brand-border hover:bg-brand-surface hover:text-brand',
        ].join(' ')}
      >
        All
      </button>
      {categories.map((cat) => (
        <button
          key={cat}
          onClick={() => onSelect(cat === selected ? null : cat)}
          className={[
            'shrink-0 rounded-full px-4 py-1.5 text-sm font-medium capitalize transition-colors',
            selected === cat
              ? 'bg-primary-600 text-on-brand'
              : 'border border-card-border bg-card-muted text-content-body hover:border-brand-border hover:bg-brand-surface hover:text-brand',
          ].join(' ')}
        >
          {cat}
        </button>
      ))}
    </div>
  )
}
