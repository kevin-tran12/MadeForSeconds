import { describe, it, expect } from 'vitest'
import { formatIngredient } from '../../src/lib/units'

describe('formatIngredient', () => {
  // ── Scaling only (no unit conversion) ────────────────────────────────────

  it('scales a whole number amount correctly', () => {
    const result = formatIngredient('2', undefined, 2, 'imperial')
    expect(result).toEqual({ amount: '4', unit: undefined })
  })

  it('formats scaled amount without trailing zeros', () => {
    const result = formatIngredient('1', undefined, 1.5, 'imperial')
    expect(result).toEqual({ amount: '1.5', unit: undefined })
  })

  it('returns original string when amount is not a number', () => {
    const result = formatIngredient('handful', undefined, 2, 'imperial')
    expect(result).toEqual({ amount: 'handful', unit: undefined })
  })

  it('returns empty amount unchanged', () => {
    const result = formatIngredient('', undefined, 2, 'imperial')
    expect(result).toEqual({ amount: '', unit: undefined })
  })

  it('passes through unrecognised units unchanged', () => {
    const result = formatIngredient('3', 'sprigs', 1, 'metric')
    expect(result).toEqual({ amount: '3', unit: 'sprigs' })
  })

  // ── Volume conversions (imperial → metric) ────────────────────────────────

  it('converts cups to ml', () => {
    const result = formatIngredient('1', 'cup', 1, 'metric')
    expect(result).toEqual({ amount: '240', unit: 'ml' })
  })

  it('converts cups to ml after scaling', () => {
    const result = formatIngredient('1', 'cups', 2, 'metric')
    expect(result).toEqual({ amount: '480', unit: 'ml' })
  })

  it('converts tablespoons to ml', () => {
    const result = formatIngredient('2', 'tbsp', 1, 'metric')
    expect(result).toEqual({ amount: '30', unit: 'ml' })
  })

  it('converts teaspoons to ml', () => {
    const result = formatIngredient('1', 'tsp', 1, 'metric')
    expect(result).toEqual({ amount: '5', unit: 'ml' })
  })

  it('converts fluid ounces to ml', () => {
    const result = formatIngredient('1', 'fl oz', 1, 'metric')
    expect(result).toEqual({ amount: '30', unit: 'ml' })
  })

  // ── Weight conversions (imperial → metric) ────────────────────────────────

  it('converts oz to g', () => {
    const result = formatIngredient('2', 'oz', 1, 'metric')
    expect(result).toEqual({ amount: '56', unit: 'g' })
  })

  it('converts lb to g', () => {
    const result = formatIngredient('1', 'lb', 1, 'metric')
    expect(result).toEqual({ amount: '453', unit: 'g' })
  })

  it('converts lbs to g', () => {
    const result = formatIngredient('0.5', 'lbs', 1, 'metric')
    expect(result.unit).toBe('g')
    expect(result.amount).toBe('227') // 0.5 * 453 = 226.5 → rounds to 227
  })

  // ── Metric → imperial (round-trip) ────────────────────────────────────────

  it('converts ml to cups when system is imperial', () => {
    const result = formatIngredient('240', 'ml', 1, 'imperial')
    expect(result).toEqual({ amount: '1', unit: 'cup' })
  })

  it('converts g to oz when system is imperial', () => {
    const result = formatIngredient('28', 'g', 1, 'imperial')
    expect(result).toEqual({ amount: '1', unit: 'oz' })
  })

  // ── Temperature ───────────────────────────────────────────────────────────

  it('converts °F to °C', () => {
    const result = formatIngredient('350', '°F', 1, 'metric')
    expect(result).toEqual({ amount: '177', unit: '°C' })
  })

  it('converts °C to °F', () => {
    const result = formatIngredient('180', '°C', 1, 'imperial')
    expect(result).toEqual({ amount: '356', unit: '°F' })
  })

  it('does not scale temperature with servings', () => {
    // Oven temp should stay the same regardless of scale
    const result = formatIngredient('350', '°F', 3, 'metric')
    expect(result.amount).toBe('177')
  })

  // ── No-op cases ───────────────────────────────────────────────────────────

  it('leaves imperial unit unchanged when system is already imperial', () => {
    const result = formatIngredient('2', 'cups', 1, 'imperial')
    expect(result).toEqual({ amount: '2', unit: 'cups' })
  })

  it('leaves metric unit unchanged when system is already metric', () => {
    const result = formatIngredient('200', 'ml', 1, 'metric')
    expect(result).toEqual({ amount: '200', unit: 'ml' })
  })

  it('leaves °F unchanged when system is imperial', () => {
    const result = formatIngredient('350', '°F', 1, 'imperial')
    expect(result).toEqual({ amount: '350', unit: '°F' })
  })

  // ── Edge cases ────────────────────────────────────────────────────────────

  it('handles fractional cups correctly', () => {
    const result = formatIngredient('0.5', 'cup', 1, 'metric')
    expect(result).toEqual({ amount: '120', unit: 'ml' })
  })

  it('rounds large metric values to whole numbers', () => {
    const result = formatIngredient('2', 'lb', 1, 'metric')
    const val = Number(result.amount)
    expect(Number.isInteger(val)).toBe(true)
    expect(result.unit).toBe('g')
  })
})
