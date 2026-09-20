import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

const { coverage, get, upsert, del } = vi.hoisted(() => ({
  coverage: vi.fn(),
  get: vi.fn(),
  upsert: vi.fn(),
  del: vi.fn(),
}))

vi.mock('../../../lib/api', () => ({
  adminIngredientApi: { coverage, get, upsert, delete: del },
}))

import { IngredientProfilesPanel } from '../IngredientProfilesPanel'

const ROWS = [
  { key: 'garlic', display: 'garlic cloves', recipes: ['Tonkotsu Ramen'], recipe_count: 1, covered: false, profile_slug: null, via: null },
  { key: 'salt', display: 'salt', recipes: ['Tonkotsu Ramen', 'Hummus'], recipe_count: 2, covered: true, profile_slug: 'salt', via: 'exact' },
]

const SALT_PROFILE = {
  slug: 'salt', name: 'Salt', aliases: ['table salt'], what_it_is: 'A mineral seasoning.',
  role: 'seasoning', substitutions: '', buying: '', storage: '', mistakes: '', allergens: '',
}

beforeEach(() => {
  coverage.mockReset().mockResolvedValue(ROWS)
  get.mockReset().mockResolvedValue(SALT_PROFILE)
  upsert.mockReset().mockResolvedValue(SALT_PROFILE)
  del.mockReset().mockResolvedValue(undefined)
})

describe('IngredientProfilesPanel', () => {
  it('loads and shows the missing ingredients by default', async () => {
    render(<IngredientProfilesPanel />)

    await waitFor(() => expect(screen.getByText('garlic cloves')).toBeTruthy())
    expect(screen.queryByText('salt')).toBeNull() // covered, excluded from the default "missing" filter
  })

  it('switching to the covered filter shows covered rows instead', async () => {
    render(<IngredientProfilesPanel />)
    await waitFor(() => expect(screen.getByText('garlic cloves')).toBeTruthy())

    fireEvent.click(screen.getByText('covered'))

    await waitFor(() => expect(screen.getByText('salt')).toBeTruthy())
    expect(screen.queryByText('garlic cloves')).toBeNull()
  })

  it('opening a covered row fetches and shows the profile in the editor', async () => {
    render(<IngredientProfilesPanel />)
    await waitFor(() => expect(screen.getByText('garlic cloves')).toBeTruthy())
    fireEvent.click(screen.getByText('covered'))
    await waitFor(() => expect(screen.getByText('salt')).toBeTruthy())

    fireEvent.click(screen.getByText('salt'))

    await waitFor(() => expect(get).toHaveBeenCalledWith('salt'))
    expect(await screen.findByDisplayValue('Salt')).toBeTruthy()
    expect(await screen.findByDisplayValue('A mineral seasoning.')).toBeTruthy()
  })

  it('opening a missing row pre-fills the name and does not call get()', async () => {
    render(<IngredientProfilesPanel />)
    await waitFor(() => expect(screen.getByText('garlic cloves')).toBeTruthy())

    fireEvent.click(screen.getByText('garlic cloves'))

    expect(get).not.toHaveBeenCalled()
    expect(await screen.findByDisplayValue('garlic cloves')).toBeTruthy()
  })

  it('save calls upsert with the slug and the edited fields', async () => {
    render(<IngredientProfilesPanel />)
    await waitFor(() => expect(screen.getByText('garlic cloves')).toBeTruthy())

    fireEvent.click(screen.getByText('garlic cloves'))
    const whatItIs = await screen.findByLabelText(/What it is/i)
    fireEvent.change(whatItIs, { target: { value: 'An allium used across the site.' } })

    fireEvent.click(screen.getByText('Save'))

    // row.key is "garlic" (already unit-stripped by services/ingredients.py's
    // primary_keys), so the derived slug for a brand-new profile is "garlic",
    // not "garlic-cloves" — the display text, not the key, carries "cloves".
    await waitFor(() => expect(upsert).toHaveBeenCalledWith(
      'garlic',
      expect.objectContaining({ name: 'garlic cloves', what_it_is: 'An allium used across the site.' }),
    ))
  })

  it('delete calls the delete endpoint for the open profile', async () => {
    render(<IngredientProfilesPanel />)
    await waitFor(() => expect(screen.getByText('garlic cloves')).toBeTruthy())
    fireEvent.click(screen.getByText('covered'))
    await waitFor(() => expect(screen.getByText('salt')).toBeTruthy())
    fireEvent.click(screen.getByText('salt'))
    await waitFor(() => expect(get).toHaveBeenCalled())

    fireEvent.click(screen.getByText('Delete'))

    await waitFor(() => expect(del).toHaveBeenCalledWith('salt'))
  })
})
