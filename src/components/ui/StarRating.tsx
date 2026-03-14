interface StarRatingProps {
  value: number | null
  onChange?: (v: number | null) => void
  readonly?: boolean
  size?: 'sm' | 'md' | 'lg'
}

const sizeClass = {
  sm: 'text-base',
  md: 'text-2xl',
  lg: 'text-3xl',
}

export function StarRating({ value, onChange, readonly = false, size = 'md' }: StarRatingProps) {
  const stars = [1, 2, 3, 4, 5]

  if (readonly) {
    return (
      <div className={`flex items-center gap-0.5 ${sizeClass[size]}`} aria-label={`Rating: ${value ?? 'none'} out of 5`}>
        {stars.map((i) => (
          <span key={i} className={i <= (value ?? 0) ? 'text-yellow-400' : 'text-gray-300'}>
            {i <= (value ?? 0) ? '★' : '☆'}
          </span>
        ))}
      </div>
    )
  }

  return (
    <div className={`flex items-center gap-1 ${sizeClass[size]}`} role="group" aria-label="Rating">
      {stars.map((i) => (
        <button
          key={i}
          type="button"
          aria-label={`Rate ${i} star${i !== 1 ? 's' : ''}`}
          onClick={() => onChange?.(value === i ? null : i)}
          className={`transition-transform hover:scale-125 focus:outline-none ${
            i <= (value ?? 0) ? 'text-yellow-400' : 'text-gray-300 hover:text-yellow-300'
          }`}
        >
          {i <= (value ?? 0) ? '★' : '☆'}
        </button>
      ))}
      {value !== null && (
        <button
          type="button"
          onClick={() => onChange?.(null)}
          className="ml-1 text-xs text-gray-400 hover:text-gray-600"
          aria-label="Clear rating"
        >
          ✕
        </button>
      )}
    </div>
  )
}
