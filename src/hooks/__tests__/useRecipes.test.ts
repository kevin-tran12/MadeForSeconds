import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useRecipes } from '../useRecipes'
import { listPublicRecipes } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  listPublicRecipes: vi.fn(),
}))

describe('useRecipes', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches recipes on mount', async () => {
    const mockRecipes = [{ id: '1', title: 'Carbonara' }]
    ;(listPublicRecipes as any).mockResolvedValue(mockRecipes)

    const { result } = renderHook(() => useRecipes())

    expect(result.current.loading).toBe(true)
    
    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.recipes).toEqual(mockRecipes)
    expect(listPublicRecipes).toHaveBeenCalled()
  })

  it('handles error state', async () => {
    ;(listPublicRecipes as any).mockRejectedValue(new Error('Fetch failed'))

    const { result } = renderHook(() => useRecipes())

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.error).toBe('Fetch failed')
    expect(result.current.recipes).toEqual([])
  })

  it('refetches when params change', async () => {
    ;(listPublicRecipes as any).mockResolvedValue([])

    const { rerender } = renderHook(
      (props: { search?: string }) => useRecipes(props),
      { initialProps: { search: '' } }
    )

    rerender({ search: 'pasta' })

    expect(listPublicRecipes).toHaveBeenCalledWith('pasta', undefined, undefined)
  })
})
