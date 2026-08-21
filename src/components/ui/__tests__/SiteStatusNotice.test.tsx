import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { SiteStatusNotice } from '../SiteStatusNotice'

describe('SiteStatusNotice', () => {
  it('names the cost cap only when the breaker confirmed it', () => {
    render(<SiteStatusNotice status={{ kind: 'budget-cap', since: null }} />)

    expect(screen.getByText(/kitchen’s closed/i)).toBeInTheDocument()
    expect(screen.getByText(/hosting budget/i)).toBeInTheDocument()
    // Reassurance matters more than the mechanism to an ordinary visitor.
    expect(screen.getByText(/nothing’s wrong on your end/i)).toBeInTheDocument()
  })

  it('shows when the pause started, if known', () => {
    render(
      <SiteStatusNotice status={{ kind: 'budget-cap', since: '2026-08-11T06:35:54Z' }} />,
    )

    expect(screen.getByText(/Paused August 11/)).toBeInTheDocument()
  })

  it('ignores an unparseable timestamp rather than rendering "Invalid Date"', () => {
    render(<SiteStatusNotice status={{ kind: 'budget-cap', since: 'not-a-date' }} />)

    expect(screen.queryByText(/Invalid Date/)).not.toBeInTheDocument()
    expect(screen.getByText(/hosting budget/i)).toBeInTheDocument()
  })

  it.each([
    ['client-offline', /offline/i],
    ['unreachable', /can’t connect/i],
    ['refused', /isn’t serving recipes/i],
  ] as const)('never blames the budget in the %s state', (kind, expected) => {
    render(<SiteStatusNotice status={{ kind } as never} />)

    expect(screen.getByText(expected)).toBeInTheDocument()
    // The whole point of the status file: only it may name the cap.
    expect(screen.queryByText(/budget/i)).not.toBeInTheDocument()
  })

  it.each(['unreachable', 'refused', 'client-offline'] as const)(
    'promises no timeframe in the %s state',
    (kind) => {
      // These states are also what a cost-cap pause looks like when status.json
      // is missing — and that lasts until the 1st, not "a few minutes".
      render(<SiteStatusNotice status={{ kind } as never} />)

      const text = screen.getByRole('status').textContent ?? ''
      expect(text).not.toMatch(/few minutes|shortly|soon|temporarily|short break/i)
    },
  )

  it('gives a timeframe only for the confirmed cost cap', () => {
    // This one we actually know: the reset job runs on the 1st.
    render(<SiteStatusNotice status={{ kind: 'budget-cap', since: null }} />)
    expect(screen.getByText(/on the 1st/i)).toBeInTheDocument()
  })

  it('points at the right party for a client-side outage', () => {
    render(<SiteStatusNotice status={{ kind: 'client-offline' }} />)
    expect(screen.getByText(/your device isn’t connected/i)).toBeInTheDocument()
  })

  it('reassures that server-side faults are not the visitor’s fault', () => {
    render(<SiteStatusNotice status={{ kind: 'refused' }} />)
    expect(screen.getByText(/not your connection/i)).toBeInTheDocument()
  })

  it('announces politely to assistive tech', () => {
    render(<SiteStatusNotice status={{ kind: 'budget-cap', since: null }} />)

    const region = screen.getByRole('status')
    expect(region).toHaveAttribute('aria-live', 'polite')
  })
})
