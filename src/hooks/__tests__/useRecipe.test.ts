import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useRecipe } from '../useRecipe'
import { getRecipe } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  getRecipe: vi.fn(),
}))

describe('useRecipe', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches recipe when slug is provided', async () => {
    const mockRecipe = { id: '1', title: 'Carbonara', slug: 'carbonara' }
    ;(getRecipe as any).mockResolvedValue(mockRecipe)

    const { result } = renderHook(() => useRecipe('carbonara'))

    expect(result.current.loading).toBe(true)
    
    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.recipe).toEqual(mockRecipe)
    expect(getRecipe).toHaveBeenCalledWith('carbonara')
  })

  it('handles 404 error', async () => {
    ;(getRecipe as any).mockRejectedValue(new Error('Recipe not found'))

    const { result } = renderHook(() => useRecipe('ghost'))

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.error).toBe('Recipe not found')
    expect(result.current.recipe).toBeNull()
    expect(result.current.isConnectionError).toBe(false)
  })

  it('flags a connectivity failure separately from a real 404', async () => {
    ;(getRecipe as any).mockRejectedValue(new TypeError('Failed to fetch'))

    const { result } = renderHook(() => useRecipe('carbonara'))

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.isConnectionError).toBe(true)
  })

  it('does not fetch if slug is undefined', () => {
    const { result } = renderHook(() => useRecipe(undefined))
    expect(result.current.loading).toBe(false)
    expect(getRecipe).not.toHaveBeenCalled()
  })
})
