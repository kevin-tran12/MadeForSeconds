import type { InputHTMLAttributes } from 'react'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  id: string
}

export function Input({ label, error, id, className = '', ...props }: InputProps) {
  return (
    <div className="flex flex-col gap-1">
      {label && (
        <label htmlFor={id} className="text-sm font-medium text-content-body">
          {label}
        </label>
      )}
      <input
        id={id}
        className={[
          'rounded-lg border px-3 py-2 text-sm outline-none transition-colors',
          'bg-control text-content placeholder:text-control-placeholder',
          error
            ? 'border-danger-border focus:border-danger focus:ring-2 focus:ring-danger-border'
            : 'border-control-border focus:border-brand focus:ring-2 focus:ring-brand-border',
          className,
        ].join(' ')}
        {...props}
      />
      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  )
}
