import type { Recipe } from '../../lib/types'

/** Starter questions built from the recipe itself, so they are always on-topic. */
export function exampleQuestions(recipe: Recipe, servings: number): string[] {
  const items = (recipe.components?.length ? recipe.components.flatMap((c) => c.ingredients) : recipe.ingredients)
    .map((i) => i.item.trim())
    .filter(Boolean)
  const questions: string[] = []
  if (items[0]) questions.push(`I don't have ${items[0]} — what can I use instead?`)
  questions.push('Can I make this ahead? How do I store leftovers?')
  questions.push(`What should I watch out for if I cook this for ${servings * 2}?`)
  if (items[1]) questions.push(`What else on this site uses ${items[1]}?`)
  return questions.slice(0, 4)
}

interface Props {
  recipe: Recipe
  servings: number
  disabled?: boolean
  onPick: (question: string) => void
}

export function ExampleQuestions({ recipe, servings, disabled = false, onPick }: Props) {
  return (
    <div className="flex flex-wrap gap-2">
      {exampleQuestions(recipe, servings).map((q) => (
        <button
          key={q}
          type="button"
          disabled={disabled}
          onClick={() => onPick(q)}
          className="rounded-full border border-card-border bg-card px-3 py-1.5 text-left text-xs text-content-body transition-colors hover:border-brand-border hover:text-brand disabled:cursor-not-allowed disabled:opacity-60"
        >
          {q}
        </button>
      ))}
    </div>
  )
}
