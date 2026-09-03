import { apiFetch, apiUpload } from './api-client'
import type { Recipe, RecipeFormData, PaginatedRecipes, GroupedRecipes } from './types'
import type { Expense, ExpenseCreate, ExpenseSummary } from './types-expense'
import type { CookingExperience, CookingLevel, MeResponse } from './types-assistant'

// ─── Public endpoints ───────────────────────────────────────────────────────

export async function listPublicRecipes(
  search?: string,
  category?: string,
  searchBy?: string,
  limit?: number,
  cursor?: string,
  label?: string,
): Promise<PaginatedRecipes> {
  const params = new URLSearchParams()
  if (search) params.set('search', search)
  if (category) params.set('category', category)
  if (label) params.set('label', label)
  if (searchBy && searchBy !== 'all') params.set('search_by', searchBy)
  if (limit) params.set('limit', String(limit))
  if (cursor) params.set('cursor', cursor)
  const qs = params.toString()
  return apiFetch<PaginatedRecipes>(`/api/recipes${qs ? `?${qs}` : ''}`)
}

export async function getGroupedRecipes(): Promise<GroupedRecipes> {
  return apiFetch<GroupedRecipes>('/api/recipes/grouped')
}

export async function getRecipe(slug: string): Promise<Recipe> {
  return apiFetch<Recipe>(`/api/recipes/${encodeURIComponent(slug)}`)
}

export async function getCategories(): Promise<string[]> {
  return apiFetch<string[]>('/api/categories')
}

export async function getPageContent(pageId: string): Promise<Record<string, string>> {
  return apiFetch<Record<string, string>>(`/api/pages/${encodeURIComponent(pageId)}`)
}

// ─── Admin endpoints ────────────────────────────────────────────────────────

export const adminApi = {
  listRecipes: (): Promise<Recipe[]> => apiFetch('/api/admin/recipes'),

  createRecipe: (data: RecipeFormData): Promise<Recipe> =>
    apiFetch('/api/admin/recipes', { method: 'POST', body: JSON.stringify(data) }),

  updateRecipe: (id: string, data: Partial<RecipeFormData>): Promise<Recipe> =>
    apiFetch(`/api/admin/recipes/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteRecipe: (id: string): Promise<void> =>
    apiFetch(`/api/admin/recipes/${id}`, { method: 'DELETE' }),

  uploadImage: (file: File): Promise<{ url: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    return apiUpload('/api/admin/upload-image', formData)
  },

  getCategories: (): Promise<string[]> =>
    apiFetch('/api/admin/categories'),

  updateCategories: (list: string[]): Promise<string[]> =>
    apiFetch('/api/admin/categories', { method: 'PUT', body: JSON.stringify({ list }) }),

  getPageContent: (pageId: string): Promise<Record<string, string>> =>
    apiFetch(`/api/admin/pages/${encodeURIComponent(pageId)}`),

  updatePageContent: (pageId: string, data: Record<string, string>): Promise<Record<string, string>> =>
    apiFetch(`/api/admin/pages/${encodeURIComponent(pageId)}`, { method: 'PUT', body: JSON.stringify({ data }) }),

  uploadReceipt: (file: File): Promise<{ url: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    return apiUpload('/api/admin/upload-receipt', formData)
  },

  deleteReceipt: (recipeId: string, url: string): Promise<void> =>
    apiFetch(`/api/admin/recipes/${recipeId}/receipts`, {
      method: 'DELETE',
      body: JSON.stringify({ url }),
    }),
}

// ─── Admin supporter moderation ─────────────────────────────────────────────

export interface PendingSupporter {
  id: string
  collection: 'subscribers' | 'donations'
  email: string
  display_name: string
  note_pending: string
  note_pending_public: boolean
}

export interface AdminSupporter {
  id: string
  collection: 'subscribers' | 'donations'
  email: string
  display_name: string
  name_enabled: boolean
  note: string | null
  note_is_public: boolean
  note_enabled: boolean
  note_pending: string | null
  total_donated_cents: number
  status: string
}

export const adminSupporterApi = {
  listPending: () => apiFetch<PendingSupporter[]>('/api/admin/supporters/pending'),
  listAll: () => apiFetch<AdminSupporter[]>('/api/admin/supporters/all'),
  approveNote: (collection: string, id: string) =>
    apiFetch<{ approved: boolean }>(`/api/admin/supporters/${collection}/${id}/approve-note`, { method: 'POST' }),
  rejectNote: (collection: string, id: string) =>
    apiFetch<{ rejected: boolean }>(`/api/admin/supporters/${collection}/${id}/reject-note`, { method: 'POST' }),
  toggleNote: (collection: string, id: string) =>
    apiFetch<{ note_enabled: boolean }>(`/api/admin/supporters/${collection}/${id}/toggle-note`, { method: 'POST' }),
  toggleName: (collection: string, id: string) =>
    apiFetch<{ name_enabled: boolean }>(`/api/admin/supporters/${collection}/${id}/toggle-name`, { method: 'POST' }),
}

// ─── TOTP 2FA endpoints ────────────────────────────────────────────────────

export const adminTotpApi = {
  getStatus: () => apiFetch<{ enabled: boolean }>('/api/admin/totp/status'),

  setup: () => apiFetch<{ secret: string; qr_code: string }>('/api/admin/totp/setup', { method: 'POST' }),

  confirmSetup: (secret: string, code: string) =>
    apiFetch<{ enabled: boolean; token: string }>('/api/admin/totp/confirm-setup', {
      method: 'POST',
      body: JSON.stringify({ secret, code }),
    }),

  verify: (code: string) =>
    apiFetch<{ token: string }>('/api/admin/totp/verify', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),

  reset: (code: string) =>
    apiFetch<{ reset: boolean }>('/api/admin/totp/reset', {
      method: 'POST',
      body: JSON.stringify({ code }),
    }),
}

// ─── Expense ledger endpoints ───────────────────────────────────────────────

export const adminExpenseApi = {
  list: (year: number, month?: number, category?: string, status = 'active') => {
    const params = new URLSearchParams({ year: String(year), status })
    if (month) params.set('month', String(month))
    if (category) params.set('category', category)
    return apiFetch<ExpenseSummary[]>(`/api/admin/expenses?${params}`)
  },

  get: (id: string) => apiFetch<Expense>(`/api/admin/expenses/${id}`),

  create: (data: ExpenseCreate) =>
    apiFetch<Expense>('/api/admin/expenses', { method: 'POST', body: JSON.stringify(data) }),

  update: (id: string, data: Partial<ExpenseCreate>) =>
    apiFetch<Expense>(`/api/admin/expenses/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  void: (id: string, reason = '') =>
    apiFetch<{ voided: boolean }>(`/api/admin/expenses/${id}/void?reason=${encodeURIComponent(reason)}`, { method: 'POST' }),

  uploadReceipt: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return apiUpload<{ receipt_url: string; receipt_filename: string; receipt_content_type: string }>(
      '/api/admin/expenses/upload-receipt',
      formData
    )
  },

  getReceiptUrl: (id: string) =>
    apiFetch<{ url: string; filename: string; content_type?: string }>(`/api/admin/expenses/${id}/receipt`),
}

// ─── Report endpoints ───────────────────────────────────────────────────────

export interface ReportSummary {
  period: string
  total_expenses: number
  total_tax: number
  total_raw: number
  expense_count: number
  by_category: Record<string, { count: number; total: number; tax: number }>
  by_month: { month: number; total: number; tax: number; count: number }[]
}

export const adminReportsApi = {
  getSummary: (year: number, month?: number) => {
    const params = new URLSearchParams({ year: String(year) })
    if (month) params.set('month', String(month))
    return apiFetch<ReportSummary>(`/api/admin/reports/summary?${params}`)
  },

  downloadCsv: (year: number, month?: number) => {
    const params = new URLSearchParams({ year: String(year) })
    if (month) params.set('month', String(month))
    return `${import.meta.env.VITE_API_URL}/api/admin/reports/export/csv?${params}`
  },

  downloadPdf: (year: number, month?: number) => {
    const params = new URLSearchParams({ year: String(year) })
    if (month) params.set('month', String(month))
    return `${import.meta.env.VITE_API_URL}/api/admin/reports/export/pdf?${params}`
  },
}

// ─── Supporter endpoints ────────────────────────────────────────────────────

export const subscriberApi = {
  createCheckout: (
    amountCents: number,
    successUrl: string,
    cancelUrl: string,
    oneTime: boolean,
    idempotencyKey: string
  ) =>
    apiFetch<{ checkout_url: string }>('/api/subscribe/checkout', {
      method: 'POST',
      body: JSON.stringify({
        amount_cents: amountCents,
        success_url: successUrl,
        cancel_url: cancelUrl,
        one_time: oneTime,
        // Caller owns the key's lifecycle so it stays stable across a single
        // logical submit attempt (see SupportPage.tsx) — lets Stripe dedupe a
        // retried/double-submitted request instead of creating two sessions.
        idempotency_key: idempotencyKey,
      }),
    }),

  getSessionInfo: (sessionId: string) =>
    apiFetch<{ email: string; payment_type: string; amount_cents: number; already_set_up: boolean }>(
      `/api/subscribe/session-info?session_id=${encodeURIComponent(sessionId)}`
    ),

  setupProfile: (data: { session_id: string; display_name: string; note: string; note_is_public: boolean }) =>
    apiFetch<{ display_name: string | null; note: string | null; note_is_public: boolean }>(
      '/api/subscribe/setup-profile',
      { method: 'POST', body: JSON.stringify(data) }
    ),

  requestCancel: (email: string) =>
    apiFetch<{ message: string }>('/api/subscribe/cancel-request', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),

  confirmCancel: (token: string) =>
    apiFetch<{ message: string }>('/api/subscribe/cancel-confirm', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),

  /** Email a signed link that attaches a past donation (made with `email`) to the reader's account. */
  linkRequest: (email: string) =>
    apiFetch<{ message: string }>('/api/subscribe/link-request', {
      method: 'POST',
      body: JSON.stringify({ email }),
    }),

  /** Finish linking; the caller must be signed in (apiFetch attaches the token). */
  linkConfirm: (token: string) =>
    apiFetch<{ message: string; linked: number; supporter: boolean }>('/api/subscribe/link-confirm', {
      method: 'POST',
      body: JSON.stringify({ token }),
    }),

  listSupporters: () =>
    apiFetch<{ display_name: string; note?: string }[]>('/api/subscribe/supporters'),
}

// ─── Reader profile (any signed-in Google account) ─────────────────────────

export const meApi = {
  /** The caller's own profile, supporter status, and Sous Chef allowance. */
  get: () => apiFetch<MeResponse>('/api/me'),

  updateExperience: (level: CookingLevel, notes: string) =>
    apiFetch<{ cooking_experience: CookingExperience }>('/api/me/experience', {
      method: 'PUT',
      body: JSON.stringify({ level, notes }),
    }),

  /** Delete-my-data: the reader record, feedback, and supporter uid links. */
  deleteData: () =>
    apiFetch<{ deleted: boolean; users_deleted: number; feedback_deleted: number; supporter_links_removed: number }>(
      '/api/me/data',
      { method: 'DELETE' }
    ),
}
