export type Difficulty = 'easy' | 'medium' | 'hard'

export interface Ingredient {
  item: string
  amount: string
  unit: string
  group?: string | null
}

export interface Instruction {
  step: number
  text: string
  tip?: string | null
}

export interface NutritionEntry {
  label: string
  value: number
  unit: string
}

/** A sub-recipe within a multi-component dish (e.g. the rice in Hainanese Chicken Rice). */
export interface RecipeComponent {
  title: string
  description?: string | null
  ingredients: Ingredient[]
  instructions: Instruction[]
  prep_time_minutes?: number | null
  cook_time_minutes?: number | null
  yield_description?: string | null
}

export interface Recipe {
  id: string
  title: string
  slug: string
  description: string
  ingredients: Ingredient[]
  instructions: Instruction[]
  prep_time_minutes: number
  cook_time_minutes: number
  servings: number
  difficulty: Difficulty
  categories: string[]
  image_url: string | null
  published: boolean
  created_at: string
  updated_at: string
  nutrition: NutritionEntry[]
  components?: RecipeComponent[] | null
}

// Omit auto-generated fields when submitting from the form
export type RecipeFormData = Omit<Recipe, 'id' | 'slug' | 'created_at' | 'updated_at'>

export interface PaginatedRecipes {
  recipes: Recipe[]
  next_cursor: string | null
}

export interface CategoryGroup {
  category: string
  recipes: Recipe[]
}

export interface GroupedRecipes {
  recent: Recipe[]
  groups: CategoryGroup[]
}
