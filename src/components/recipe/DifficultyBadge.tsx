import type { Difficulty } from '../../lib/types'
import { Badge } from '../ui/Badge'

const config: Record<Difficulty, { label: string; variant: 'success' | 'warning' | 'danger' }> = {
  easy: { label: 'Easy', variant: 'success' },
  medium: { label: 'Medium', variant: 'warning' },
  hard: { label: 'Hard', variant: 'danger' },
}

export function DifficultyBadge({ difficulty }: { difficulty: Difficulty }) {
  const { label, variant } = config[difficulty]
  return <Badge variant={variant}>{label}</Badge>
}
