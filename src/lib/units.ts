export type UnitSystem = 'imperial' | 'metric'

interface Conv {
  imp: string
  met: string
  factor: number // 1 imperial unit = factor metric units
}

const CONVERSIONS: Conv[] = [
  { imp: 'cup',    met: 'ml', factor: 240  },
  { imp: 'cups',   met: 'ml', factor: 240  },
  { imp: 'tbsp',   met: 'ml', factor: 15   },
  { imp: 'tsp',    met: 'ml', factor: 5    },
  { imp: 'oz',     met: 'g',  factor: 28   },
  { imp: 'lb',     met: 'g',  factor: 453  },
  { imp: 'lbs',    met: 'g',  factor: 453  },
  { imp: 'fl oz',  met: 'ml', factor: 30   },
  { imp: 'pt',     met: 'ml', factor: 473  },
  { imp: 'qt',     met: 'ml', factor: 946  },
]

function fmt(n: number): string {
  if (n >= 100) return Math.round(n).toString()
  if (n >= 10) return Math.round(n).toString()
  const r = Math.round(n * 10) / 10
  return Number.isInteger(r) ? r.toString() : r.toFixed(1)
}

/**
 * Scale an ingredient amount and optionally convert its unit.
 * Temperatures are not scaled (oven temp doesn't change with servings).
 * Returns the original amount/unit unchanged for unrecognised units.
 */
export function formatIngredient(
  rawAmount: string,
  unit: string | undefined,
  scale: number,
  system: UnitSystem,
): { amount: string; unit: string | undefined } {
  const num = parseFloat(rawAmount)
  const scaled = isNaN(num) ? NaN : num * scale
  const scaledStr = isNaN(scaled)
    ? rawAmount
    : Number.isInteger(scaled)
    ? scaled.toString()
    : scaled.toFixed(2).replace(/\.?0+$/, '')

  if (!unit) return { amount: scaledStr, unit }
  const u = unit.toLowerCase().trim()

  // Temperature: use raw (unscaled) value
  if (!isNaN(num)) {
    if (u === '°f' && system === 'metric') {
      return { amount: Math.round((num - 32) * 5 / 9).toString(), unit: '°C' }
    }
    if (u === '°c' && system === 'imperial') {
      return { amount: Math.round(num * 9 / 5 + 32).toString(), unit: '°F' }
    }
  }

  if (isNaN(scaled)) return { amount: scaledStr, unit }
  const conv = CONVERSIONS.find((c) => c.imp === u || c.met === u)
  if (!conv) return { amount: scaledStr, unit }

  if (system === 'metric' && conv.imp === u) {
    return { amount: fmt(scaled * conv.factor), unit: conv.met }
  }
  if (system === 'imperial' && conv.met === u) {
    return { amount: fmt(scaled / conv.factor), unit: conv.imp }
  }
  return { amount: scaledStr, unit }
}
