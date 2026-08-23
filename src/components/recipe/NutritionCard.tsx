import type { NutritionEntry } from '../../lib/types'

// Labels that are considered "primary" (displayed bold at full width)
const PRIMARY_LABELS = new Set([
  'calories', 'total fat', 'total carbohydrate', 'protein', 'sodium', 'cholesterol',
])

// Labels that are sub-nutrients (displayed indented under their parent)
const SUB_LABELS = new Set([
  'saturated fat', 'trans fat', 'dietary fiber', 'total sugars', 'added sugars',
  'vitamin d', 'calcium', 'iron', 'potassium',
])

// Approximate % Daily Values based on a 2,000-calorie diet (FDA reference)
const DAILY_VALUES: Record<string, number> = {
  'total fat': 78,
  'saturated fat': 20,
  'cholesterol': 300,
  'sodium': 2300,
  'total carbohydrate': 275,
  'dietary fiber': 28,
  'protein': 50,
  'vitamin d': 20,
  'calcium': 1300,
  'iron': 18,
  'potassium': 4700,
}

function formatValue(value: number): string {
  if (Number.isInteger(value)) return String(value)
  return value % 1 < 0.05 ? String(Math.round(value)) : value.toFixed(1)
}

function dailyPct(label: string, value: number): number | null {
  const dv = DAILY_VALUES[label.toLowerCase()]
  if (!dv) return null
  return Math.round((value / dv) * 100)
}

interface NutritionCardProps {
  nutrition: NutritionEntry[]
  scale?: number
}

export function NutritionCard({ nutrition, scale = 1 }: NutritionCardProps) {
  const entries = nutrition
    .filter((n) => n.label)
    .map((n) => ({ ...n, value: n.value * scale }))

  if (entries.length === 0) return null

  const servingLabel = scale === 1 ? 'Per serving' : `Per ${formatValue(scale)} servings`

  // Split into calories row (special large display) and the rest
  const caloriesEntry = entries.find((e) => e.label.toLowerCase() === 'calories')
  const rest = entries.filter((e) => e.label.toLowerCase() !== 'calories')

  return (
    <section className="mt-10 overflow-hidden rounded-3xl border-2 border-content bg-card shadow-sm">
      {/* Header */}
      <div className="border-b-8 border-content px-5 pt-4 pb-1">
        <h2 className="font-display text-3xl font-black tracking-tight text-content">
          Nutrition Facts
        </h2>
        <p className="text-sm text-content-muted">{servingLabel}</p>
      </div>

      {/* Calories — big display */}
      {caloriesEntry && (
        <div className="flex items-end justify-between border-b-4 border-content px-5 py-2">
          <span className="text-sm font-bold text-content">Calories</span>
          <span className="font-display text-4xl font-black text-content">
            {formatValue(caloriesEntry.value)}
          </span>
        </div>
      )}

      {/* % Daily Value header */}
      {rest.length > 0 && (
        <div className="border-b border-card-border px-5 py-1 text-right">
          <span className="text-xs font-bold text-content-muted">% Daily Value*</span>
        </div>
      )}

      {/* Nutrient rows */}
      <div className="divide-y divide-card-border px-5">
        {rest.map(({ label, value, unit }) => {
          const lower = label.toLowerCase()
          const isPrimary = PRIMARY_LABELS.has(lower)
          const isSub = SUB_LABELS.has(lower)
          const pct = dailyPct(lower, value)

          return (
            <div
              key={label}
              className={`flex items-center justify-between py-1 ${isSub ? 'pl-5' : ''}`}
            >
              <span
                className={`text-sm ${isPrimary ? 'font-bold' : 'font-normal'} text-content`}
              >
                {label}
                {unit && (
                  <span className="ml-1 font-normal text-content-muted">
                    {formatValue(value)}{unit}
                  </span>
                )}
              </span>
              {pct !== null ? (
                <span className="text-sm font-bold text-content">{pct}%</span>
              ) : (
                !unit && (
                  <span className="text-sm font-normal text-content-body">
                    {formatValue(value)}
                  </span>
                )
              )}
            </div>
          )
        })}
      </div>

      {/* Footer */}
      {rest.some((e) => dailyPct(e.label.toLowerCase(), e.value) !== null) && (
        <div className="border-t-4 border-content px-5 py-2">
          <p className="text-xs text-content-muted">
            * The % Daily Value tells you how much a nutrient in a serving of food
            contributes to a daily diet. 2,000 calories a day is used for general
            nutrition advice.
          </p>
        </div>
      )}
    </section>
  )
}
