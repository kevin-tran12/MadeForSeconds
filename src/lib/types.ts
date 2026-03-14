export type Difficulty = 'easy' | 'medium' | 'hard'

export interface Ingredient {
  item: string
  amount: string
  unit: string
}

export interface Instruction {
  step: number
  text: string
}

export interface Nutrition {
  calories: number | null
  protein: number | null
  carbs: number | null
  fat: number | null
  fiber: number | null
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
  nutrition: Nutrition | null
}

// Omit auto-generated fields when submitting from the form
export type RecipeFormData = Omit<Recipe, 'id' | 'slug' | 'created_at' | 'updated_at'>
