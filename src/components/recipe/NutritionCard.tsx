import type { Nutrition } from '../../lib/types'

export function NutritionCard({ nutrition }: { nutrition: Nutrition }) {
  const rows: { label: string; value: number | null; unit: string }[] = [
    { label: 'Calories', value: nutrition.calories, unit: 'kcal' },
    { label: 'Protein', value: nutrition.protein, unit: 'g' },
    { label: 'Carbohydrates', value: nutrition.carbs, unit: 'g' },
    { label: 'Fat', value: nutrition.fat, unit: 'g' },
    { label: 'Fiber', value: nutrition.fiber, unit: 'g' },
  ].filter((r) => r.value !== null)

  if (rows.length === 0) return null

  return (
    <section className="mt-10 rounded-3xl border border-gray-100 bg-white p-8 shadow-sm">
      <h2 className="font-display text-xl font-bold text-gray-900 underline decoration-primary-200 decoration-4 underline-offset-8">
        Nutrition
      </h2>
      <p className="mt-1 text-xs text-gray-400 uppercase tracking-widest font-bold">Per serving</p>
      <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-5">
        {rows.map(({ label, value, unit }) => (
          <div key={label} className="flex flex-col items-center rounded-2xl bg-surface-dark p-4 text-center">
            <span className="font-display text-2xl font-bold text-gray-900">
              {value}
              <span className="text-sm font-medium text-gray-400 ml-0.5">{unit}</span>
            </span>
            <span className="mt-1 text-xs font-bold uppercase tracking-widest text-gray-500">{label}</span>
          </div>
        ))}
      </div>
    </section>
  )
}
