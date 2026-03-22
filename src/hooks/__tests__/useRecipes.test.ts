import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useRecipes } from '../useRecipes'
import { listPublicRecipes, getGroupedRecipes } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  listPublicRecipes: vi.fn(),
  getGroupedRecipes: vi.fn(),
}))

describe('useRecipes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches grouped recipes on mount (no filters)', async () => {
    const mockGrouped = { recent: [{ id: '1', title: 'Carbonara' }], groups: [] }
    ;(getGroupedRecipes as any).mockResolvedValue(mockGrouped)

    const { result } = renderHook(() => useRecipes())

    expect(result.current.loading).toBe(true)

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.grouped).toEqual(mockGrouped)
    expect(getGroupedRecipes).toHaveBeenCalled()
  })

  it('handles error state', async () => {
    ;(getGroupedRecipes as any).mockRejectedValue(new Error('Fetch failed'))

    const { result } = renderHook(() => useRecipes())

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.error).toBe('Fetch failed')
    expect(result.current.recipes).toEqual([])
  })

  it('refetches with listPublicRecipes when search param changes', async () => {
    ;(getGroupedRecipes as any).mockResolvedValue({ recent: [], groups: [] })
    ;(listPublicRecipes as any).mockResolvedValue({ recipes: [], next_cursor: null })

    const { rerender } = renderHook(
      (props: { search?: string }) => useRecipes(props),
      { initialProps: { search: '' } }
    )

    rerender({ search: 'pasta' })

    await waitFor(() => {
      expect(listPublicRecipes).toHaveBeenCalledWith('pasta', undefined, undefined, 12)
    })
  })
})
