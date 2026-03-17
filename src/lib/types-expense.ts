export const EXPENSE_CATEGORIES = [
  { value: 'ingredients', label: 'Ingredients' },
  { value: 'equipment', label: 'Equipment' },
  { value: 'hosting', label: 'Hosting / Infra' },
  { value: 'marketing', label: 'Marketing' },
  { value: 'software', label: 'Software' },
  { value: 'other', label: 'Other' },
] as const

export type ExpenseCategory = (typeof EXPENSE_CATEGORIES)[number]['value']

export interface ExpenseItem {
  name: string
  quantity: number
  unit_price: number // cents
  total_price: number // cents
  project_related: boolean
}

export interface ExpenseCreate {
  date: string // ISO
  vendor: string
  category: ExpenseCategory
  description: string
  recipe_id: string | null
  purpose: string | null
  items: ExpenseItem[]
  raw_subtotal: number
  raw_tax: number
  raw_total: number
}

export interface Expense {
  id: string
  date: string
  vendor: string
  category: ExpenseCategory
  description: string
  recipe_id: string | null
  purpose: string | null
  receipt_url: string | null
  receipt_filename: string | null
  receipt_content_type: string | null
  raw_subtotal: number
  raw_tax: number
  raw_total: number
  items: ExpenseItem[]
  project_subtotal: number
  project_tax: number
  project_total: number
  status: 'active' | 'voided'
  voided_at: string | null
  void_reason: string | null
  created_at: string
  updated_at: string
  revision: number
  ai_parsed: boolean
}

export interface ExpenseSummary {
  id: string
  date: string
  vendor: string
  category: ExpenseCategory
  description: string
  recipe_id: string | null
  purpose: string | null
  receipt_filename: string | null
  raw_total: number
  project_total: number
  project_tax: number
  status: 'active' | 'voided'
  created_at: string
}

/** Format cents to dollar string */
export function formatCents(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`
}

/** Recalculate project amounts client-side for live preview */
export function recalcProjectAmounts(
  items: ExpenseItem[],
  rawTax: number,
  rawSubtotal: number
): { projectSubtotal: number; projectTax: number; projectTotal: number } {
  const projectSubtotal = items
    .filter((i) => i.project_related)
    .reduce((sum, i) => sum + i.total_price, 0)

  const projectTax = rawSubtotal > 0 ? Math.round(rawTax * (projectSubtotal / rawSubtotal)) : 0

  return {
    projectSubtotal,
    projectTax,
    projectTotal: projectSubtotal + projectTax,
  }
}
