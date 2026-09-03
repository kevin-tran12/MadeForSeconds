// Types for the reader profile (/api/me) and the Sous Chef assistant.

export type CookingLevel = 'beginner' | 'home_cook' | 'confident' | 'professional'

export const COOKING_LEVELS: { value: CookingLevel; label: string; hint: string }[] = [
  { value: 'beginner', label: 'Beginner', hint: 'Spell it out — terms, technique, the common slip-ups.' },
  { value: 'home_cook', label: 'Home cook', hint: 'I know the basics; focus on the decisions that matter.' },
  { value: 'confident', label: 'Confident', hint: 'Keep it tight and technique-level.' },
  { value: 'professional', label: 'Professional', hint: 'Peer to peer: ratios, temperatures, no hand-holding.' },
]

export interface CookingExperience {
  level: CookingLevel
  notes: string
  updated_at: string | null
}

export interface QuotaScope {
  limit: number
  used: number
}

export interface QuotaInfo {
  supporter: boolean
  day: QuotaScope
  month: QuotaScope | null
  remaining: number
  resets_at: string
}

/** GET /api/me — only ever the caller's own record. */
export interface MeResponse {
  email: string
  is_admin: boolean
  supporter: boolean
  returning: boolean
  answers_total: number
  cooking_experience: CookingExperience | null
  assistant: QuotaInfo
}

export interface AssistantStatus {
  configured: boolean
  paused: boolean
  resets_at: string
  quotas: { free: number; supporter: number; supporter_monthly: number }
  levels: CookingLevel[]
}

/** What a clarifying question is about. `location` is only ever a zip code. */
export type ClarifyKind = 'location' | 'equipment' | 'quantity' | 'diet' | 'other'

export interface ClarifyQuestion {
  text: string
  kind: ClarifyKind
}

export interface ClarifyAnswer {
  kind: ClarifyKind
  text: string
}

export interface AskRequest {
  slug: string
  question: string
  history: { role: 'user' | 'assistant'; content: string }[]
  context: {
    servings: number
    unit_system: 'imperial' | 'metric'
    /** True for every send after the chef asked its questions: one round per thread. */
    clarified?: boolean
    answers?: ClarifyAnswer[]
  }
}

export interface AskUsage {
  input_tokens: number
  cache_creation_input_tokens: number
  cache_read_input_tokens: number
  output_tokens: number
}

export interface AskDoneEvent {
  usage: AskUsage | null
  cost_micro_usd: number
  stop_reason: string | null
  truncated: boolean
  refused: boolean
  /** Server-side web searches the answer ran; billed per search, not per token. */
  searches: number
  /** Which specialist answered: technique, ingredients, safety, scaling, sourcing, catalogue, general, offtopic. */
  spoke: string
  /** True when the chef asked the reader something instead of answering; the question is refunded. */
  clarifying: boolean
  quota: QuotaInfo
}

export type AskErrorCode =
  | 'not_configured'
  | 'sign_in_required'
  | 'quota_exhausted'
  | 'spend_cap'
  | 'budget_unavailable'
  | 'rate_limited'
  | 'invalid_question'
  | 'personal_info'
  | 'prompt_too_long'
  | 'recipe_not_found'
  | 'upstream_busy'
  | 'upstream_error'
  | 'refused'
  | 'network'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  pending?: boolean
  truncated?: boolean
  refused?: boolean
  rated?: 'up' | 'down'
  /** Present while this bubble is waiting on the reader's answers. */
  clarify?: ClarifyQuestion[]
}
