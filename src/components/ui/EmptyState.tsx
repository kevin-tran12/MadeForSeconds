import type { ReactNode } from 'react'

interface EmptyStateProps {
  title: string
  message?: string
  action?: ReactNode
}

export function EmptyState({ title, message, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-16 text-center">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-surface-dark text-4xl">
        🍽️
      </div>
      <div>
        <h3 className="text-lg font-semibold text-gray-800">{title}</h3>
        {message && <p className="mt-1 text-sm text-gray-500">{message}</p>}
      </div>
      {action && <div>{action}</div>}
    </div>
  )
}
