import type { SiteStatus } from '../../lib/site-status'

interface SiteStatusNoticeProps {
  status: SiteStatus
}

/**
 * Explains an API outage in the visitor's terms.
 *
 * The copy is deliberately graded by confidence. Only `budget-cap` — which the
 * breaker itself published to a bucket that stays up while Cloud Run is
 * refusing — names the cost cap. Every other state gets honest, non-committal
 * wording, because "server refused us" and "something broke" are genuinely
 * indistinguishable from the browser, and confidently blaming the budget during
 * a real outage would be a lie.
 */
function copyFor(status: SiteStatus): { emoji: string; title: string; body: string } {
  switch (status.kind) {
    case 'budget-cap':
      return {
        emoji: '🧑‍🍳',
        title: 'The kitchen’s closed for the month',
        body: sinceSuffix(
          'This site runs on a small fixed hosting budget, and it’s reached its cap. ' +
            'It comes back automatically on the 1st. Nothing’s broken — and nothing’s wrong on your end.',
          status.since,
        ),
      }
    case 'client-offline':
      return {
        emoji: '📡',
        title: 'You’re offline',
        body: 'Your device isn’t connected to the internet. Recipes will load again once you’re back.',
      }
    // Neither state below may promise a timeframe. Both are also what a
    // cost-cap pause looks like when status.json is missing (breaker failed to
    // write it, or VITE_STATUS_URL is unset) — and that outage lasts until the
    // 1st, not "a few minutes". Say what is known; never guess at a duration.
    case 'unreachable':
      return {
        emoji: '🍳',
        title: 'Can’t reach the kitchen',
        body: 'We can’t connect to the server right now. This is on our end, not your connection.',
      }
    case 'refused':
      return {
        emoji: '🍳',
        title: 'The kitchen’s closed right now',
        body: 'The site isn’t serving recipes at the moment. This is on our end, not your connection.',
      }
  }
}

function sinceSuffix(body: string, since: string | null): string {
  if (!since) return body
  const date = new Date(since)
  if (Number.isNaN(date.getTime())) return body
  return `${body} (Paused ${date.toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
  })}.)`
}

export function SiteStatusNotice({ status }: SiteStatusNoticeProps) {
  const { emoji, title, body } = copyFor(status)
  // Only the cost cap is a planned, understood state; the rest are faults.
  const planned = status.kind === 'budget-cap'

  return (
    <div
      // polite, not assertive: the visitor is not mid-task and this must not
      // interrupt a screen reader mid-sentence.
      role="status"
      aria-live="polite"
      // notice-* and card-* are flipping token pairs, so text-content stays
      // legible in both themes. A raw primary-50 here reads as light-on-light
      // in dark mode.
      className={`border-b ${
        planned
          ? 'border-notice-border bg-notice-surface'
          : 'border-card-border bg-card-muted'
      }`}
    >
      <div className="mx-auto flex max-w-6xl items-start gap-3 px-4 py-3 sm:items-center">
        <span aria-hidden="true" className="text-xl leading-none">
          {emoji}
        </span>
        <div className="min-w-0">
          <p className="font-display text-sm font-semibold text-content">{title}</p>
          <p className="mt-0.5 text-sm text-content-body">{body}</p>
        </div>
      </div>
    </div>
  )
}
