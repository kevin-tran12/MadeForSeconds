import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { useCategories } from '../useCategories'
import { getCategories } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  getCategories: vi.fn(),
}))

describe('useCategories', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('fetches categories on mount', async () => {
    const mockCats = ['Italian', 'Pasta']
    ;(getCategories as any).mockResolvedValue(mockCats)

    const { result } = renderHook(() => useCategories())

    expect(result.current.loading).toBe(true)
    
    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.categories).toEqual(mockCats)
  })

  it('handles empty list', async () => {
    ;(getCategories as any).mockResolvedValue([])

    const { result } = renderHook(() => useCategories())

    await waitFor(() => {
      expect(result.current.loading).toBe(false)
    })

    expect(result.current.categories).toEqual([])
  })
})
