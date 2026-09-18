import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { NutritionCard } from '../NutritionCard'

function renderCard(entries: { label: string; value: number; unit: string }[], scale = 1) {
  return render(
    <MemoryRouter>
      <NutritionCard nutrition={entries} scale={scale} />
    </MemoryRouter>,
  )
}

describe('NutritionCard', () => {
  it('always shows the estimate note, even with no % Daily Value rows', () => {
    // Calories alone has no %DV row, which used to mean no footer rendered at
    // all — the estimate note must not be conditional on that.
    renderCard([{ label: 'Calories', value: 500, unit: 'kcal' }])

    expect(screen.getByText(/Values are estimates/i)).toBeInTheDocument()
    expect(screen.queryByText(/% Daily Value tells you/i)).not.toBeInTheDocument()
  })

  it('shows both notes when a nutrient has a daily percentage', () => {
    renderCard([
      { label: 'Calories', value: 500, unit: 'kcal' },
      { label: 'Sodium', value: 1000, unit: 'mg' },
    ])

    expect(screen.getByText(/% Daily Value tells you/i)).toBeInTheDocument()
    expect(screen.getByText(/Values are estimates/i)).toBeInTheDocument()
  })

  it('links the estimate note to the disclaimer page', () => {
    renderCard([{ label: 'Calories', value: 500, unit: 'kcal' }])

    expect(screen.getByRole('link', { name: /disclaimer/i })).toHaveAttribute(
      'href',
      '/disclaimer/',
    )
  })

  it('scales values by the serving multiplier', () => {
    renderCard([{ label: 'Calories', value: 500, unit: 'kcal' }], 2)

    expect(screen.getByText('1000')).toBeInTheDocument()
  })
})
