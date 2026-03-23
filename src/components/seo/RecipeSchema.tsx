import { useEffect } from 'react'
import type { Recipe } from '../../lib/types'

const SITE_URL = 'https://madeforseconds.pages.dev'

function isoDuration(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h > 0 && m > 0) return `PT${h}H${m}M`
  if (h > 0) return `PT${h}H`
  return `PT${m}M`
}

export function RecipeSchema({ recipe }: { recipe: Recipe }) {
  useEffect(() => {
    const schema: Record<string, unknown> = {
      '@context': 'https://schema.org',
      '@type': 'Recipe',
      name: recipe.title,
      description: recipe.description,
      url: `${SITE_URL}/recipes/${recipe.slug}`,
      datePublished: recipe.created_at,
      prepTime: isoDuration(recipe.prep_time_minutes),
      cookTime: isoDuration(recipe.cook_time_minutes),
      totalTime: isoDuration(recipe.prep_time_minutes + recipe.cook_time_minutes),
      recipeYield: `${recipe.servings} serving${recipe.servings !== 1 ? 's' : ''}`,
      recipeCategory: recipe.categories[0] ?? undefined,
      recipeIngredient: recipe.ingredients.map(
        (ing) => [ing.amount, ing.unit, ing.item].filter(Boolean).join(' ')
      ),
      recipeInstructions: recipe.instructions.map((inst) => ({
        '@type': 'HowToStep',
        position: inst.step,
        text: inst.text,
      })),
    }

    if (recipe.image_url) schema.image = recipe.image_url

    if (recipe.nutrition && recipe.nutrition.length > 0) {
      const cal = recipe.nutrition.find((n) => n.label.toLowerCase().includes('calor'))
      const protein = recipe.nutrition.find((n) => n.label.toLowerCase().includes('protein'))
      const carbs = recipe.nutrition.find((n) => n.label.toLowerCase().includes('carb'))
      const fat = recipe.nutrition.find((n) => n.label.toLowerCase().includes('fat'))
      const fiber = recipe.nutrition.find((n) => n.label.toLowerCase().includes('fiber'))
      schema.nutrition = {
        '@type': 'NutritionInformation',
        ...(cal && { calories: `${cal.value} ${cal.unit || 'kcal'}` }),
        ...(protein && { proteinContent: `${protein.value} ${protein.unit || 'g'}` }),
        ...(carbs && { carbohydrateContent: `${carbs.value} ${carbs.unit || 'g'}` }),
        ...(fat && { fatContent: `${fat.value} ${fat.unit || 'g'}` }),
        ...(fiber && { fiberContent: `${fiber.value} ${fiber.unit || 'g'}` }),
      }
    }

    const el = document.createElement('script')
    el.type = 'application/ld+json'
    el.id = 'recipe-schema'
    el.textContent = JSON.stringify(schema)
    document.head.appendChild(el)

    return () => {
      document.getElementById('recipe-schema')?.remove()
    }
  }, [recipe])

  return null
}
