import type { QuotaInfo } from '../../lib/types-assistant'

export function QuotaBadge({ quota }: { quota: QuotaInfo }) {
  const dayLeft = Math.max(quota.day.limit - quota.day.used, 0)
  const monthLeft = quota.month ? Math.max(quota.month.limit - quota.month.used, 0) : null
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full bg-card-muted px-2.5 py-1 text-xs font-medium text-content-muted"
      title={quota.supporter ? 'Supporter allowance' : 'Free allowance'}
    >
      {quota.supporter && <span className="text-brand">Supporter ·</span>}
      {dayLeft} of {quota.day.limit} today
      {monthLeft !== null && <span> · {monthLeft} this month</span>}
    </span>
  )
}
