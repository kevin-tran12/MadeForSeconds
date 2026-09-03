import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'
import type { Recipe } from '../../../lib/types'

vi.mock('../../../hooks/useCategories', () => ({
  useCategories: () => ({ categories: [], loading: false }),
}))
vi.mock('../../../lib/api', () => ({
  adminApi: { uploadImage: vi.fn(), uploadReceipt: vi.fn(), deleteReceipt: vi.fn() },
  getCategories: vi.fn(),
}))

import { RecipeForm } from '../RecipeForm'

const existing: Recipe = {
  id: 'r1',
  title: 'Fried Rice',
  slug: 'fried-rice',
  description: 'Weeknight fried rice',
  ingredients: [{ item: 'rice', amount: '2', unit: 'cups' }],
  instructions: [{ step: 1, text: 'Fry it' }],
  prep_time_minutes: 5,
  cook_time_minutes: 10,
  servings: 2,
  difficulty: 'easy',
  categories: [],
  image_url: null,
  published: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  nutrition: [],
  sous_chef_notes: 'Use day-old rice',
}

describe('RecipeForm sous chef notes', () => {
  it('prefills the owner notes and submits them', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const { container } = render(<RecipeForm recipe={existing} onSubmit={onSubmit} isSubmitting={false} />)

    const notes = screen.getByLabelText('Sous Chef notes') as HTMLTextAreaElement
    expect(notes.value).toBe('Use day-old rice')

    fireEvent.change(notes, { target: { value: '  Thai basil works; dried galangal does not.  ' } })
    fireEvent.submit(container.querySelector('form')!)

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0][0].sous_chef_notes).toBe('Thai basil works; dried galangal does not.')
  })

  it('submits null when the notes are blank', async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined)
    const { container } = render(
      <RecipeForm recipe={{ ...existing, sous_chef_notes: null }} onSubmit={onSubmit} isSubmitting={false} />
    )
    expect((screen.getByLabelText('Sous Chef notes') as HTMLTextAreaElement).value).toBe('')
    fireEvent.submit(container.querySelector('form')!)
    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0][0].sous_chef_notes).toBeNull()
  })
})
