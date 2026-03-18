import { describe, it, expect } from 'vitest'
import { formatCents, recalcProjectAmounts, type ExpenseItem } from '../types-expense'

describe('types-expense', () => {
  describe('formatCents', () => {
    it('formats 100 to $1.00', () => {
      expect(formatCents(100)).toBe('$1.00')
    })

    it('formats 1234 to $12.34', () => {
      expect(formatCents(1234)).toBe('$12.34')
    })
    
    it('formats 0 to $0.00', () => {
      expect(formatCents(0)).toBe('$0.00')
    })
  })

  describe('recalcProjectAmounts', () => {
    it('calculates proportional tax correctly', () => {
      const items: ExpenseItem[] = [
        { name: 'A', total_price: 1000, project_related: true, quantity: 1, unit_price: 1000 },
        { name: 'B', total_price: 2000, project_related: false, quantity: 1, unit_price: 2000 },
      ]
      // Subtotal = 3000, Project = 1000
      // Tax = 300, Proportional = 300 * (1000/3000) = 100
      const result = recalcProjectAmounts(items, 300, 3000)
      expect(result.projectSubtotal).toBe(1000)
      expect(result.projectTax).toBe(100)
      expect(result.projectTotal).toBe(1100)
    })

    it('returns 0 for zero items', () => {
      const result = recalcProjectAmounts([], 100, 1000)
      expect(result.projectSubtotal).toBe(0)
      expect(result.projectTax).toBe(0)
    })

    it('handles zero subtotal (div by zero check)', () => {
      const result = recalcProjectAmounts([], 100, 0)
      expect(result.projectTax).toBe(0)
    })
  })
})
