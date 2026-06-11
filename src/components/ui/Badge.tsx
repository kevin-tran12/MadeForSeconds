import type { ReactNode } from 'react'

type Variant = 'default' | 'primary' | 'success' | 'warning' | 'danger'

interface BadgeProps {
  children: ReactNode
  variant?: Variant
  className?: string
}

const variantClasses: Record<Variant, string> = {
  default: 'bg-gray-100 dark:bg-stone-700 text-gray-700 dark:text-stone-300',
  primary: 'bg-primary-100 dark:bg-primary-950 text-primary-800 dark:text-primary-300',
  success: 'bg-green-100 dark:bg-green-950 text-green-800 dark:text-green-300',
  warning: 'bg-yellow-100 dark:bg-yellow-950 text-yellow-800 dark:text-yellow-300',
  danger: 'bg-red-100 dark:bg-red-950 text-red-800 dark:text-red-300',
}

export function Badge({ children, variant = 'default', className = '' }: BadgeProps) {
  return (
    <span
      className={[
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
        variantClasses[variant],
        className,
      ].join(' ')}
    >
      {children}
    </span>
  )
}
