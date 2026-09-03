import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Recipe } from '../../lib/types'
import type { UnitSystem } from '../../lib/units'
import { useAuth } from '../../hooks/useAuth'
import { useSousChef } from '../../hooks/useSousChef'
import { meApi } from '../../lib/api'
import { COOKING_LEVELS, type CookingLevel, type QuotaInfo } from '../../lib/types-assistant'
import { GoogleSignInButton } from '../auth/GoogleSignInButton'
import { LoadingSpinner } from '../ui/LoadingSpinner'
import { Button } from '../ui/Button'
import { QuotaBadge } from './QuotaBadge'
import { MessageList } from './MessageList'
import { Composer } from './Composer'
import { ExampleQuestions } from './ExampleQuestions'
import { ExperienceEditor } from './ExperienceEditor'

interface Props {
  recipe: Recipe
  servings: number
  unitSystem: UnitSystem
  onClose: () => void
}

function Notice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-card-border bg-card-muted p-5 text-center">
      <h3 className="font-display text-lg font-semibold text-content">{title}</h3>
      <div className="mt-2 text-sm text-content-muted">{children}</div>
    </div>
  )
}

function formatReset(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? 'later' : d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric' })
}

export function SousChefDrawer({ recipe, servings, unitSystem, onClose }: Props) {
  const { user, me, meLoading, firstName, returning, loginGoogle, refreshMe } = useAuth()
  const chef = useSousChef(recipe, { servings, unitSystem })
  const [signingIn, setSigningIn] = useState(false)
  const [editingExperience, setEditingExperience] = useState(false)
  const [deleting, setDeleting] = useState(false)

  // Escape closes; lock the page behind the drawer while it is open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [onClose])

  const quota: QuotaInfo | null = chef.quota ?? me?.assistant ?? null
  const experience = me?.cooking_experience ?? null
  const firstRun = !!user && !meLoading && !!me && !experience
  const levelLabel = COOKING_LEVELS.find((l) => l.value === experience?.level)?.label

  async function handleSignIn() {
    setSigningIn(true)
    try {
      await loginGoogle()
    } finally {
      setSigningIn(false)
    }
  }

  async function saveExperience(level: CookingLevel, notes: string) {
    await meApi.updateExperience(level, notes)
    await refreshMe()
    setEditingExperience(false)
  }

  async function deleteMyData() {
    if (!window.confirm('Delete your Sous Chef data? This removes your cooking experience, your feedback, and the link between your donations and this account. You stay signed in.')) return
    setDeleting(true)
    try {
      await meApi.deleteData()
      chef.reset()
      await refreshMe()
    } finally {
      setDeleting(false)
    }
  }

  const exhausted = quota !== null && quota.remaining <= 0
  const quotaError = chef.error?.code === 'quota_exhausted'
  const signInNeeded = !user || chef.error?.code === 'sign_in_required'

  let body: React.ReactNode
  if (chef.statusLoading || (user && meLoading)) {
    body = <LoadingSpinner className="py-12" />
  } else if (chef.status && !chef.status.configured) {
    body = (
      <Notice title="The Sous Chef is taking a break">
        Everything you need is already in the recipe — check back another day for a hand.
      </Notice>
    )
  } else if (chef.status?.paused) {
    body = (
      <Notice title="Paused until the 1st">
        The Sous Chef has used this month's budget. Supporters keep it running — thank you.
      </Notice>
    )
  } else if (signInNeeded) {
    body = (
      <div className="flex flex-col gap-4">
        <p className="text-sm text-content-body">
          Stuck on a step, out of an ingredient, cooking for a crowd? Ask the Sous Chef — a professional chef who
          loves to teach and knows this recipe inside out.
        </p>
        <ExampleQuestions recipe={recipe} servings={servings} disabled onPick={() => undefined} />
        <GoogleSignInButton onClick={handleSignIn} loading={signingIn} label="Sign in with Google to ask" />
        <p className="text-xs text-content-muted">
          We use your Google email only to count your daily questions and match your donation. You can delete
          everything the Sous Chef keeps about you at any time.
        </p>
      </div>
    )
  } else if (firstRun || editingExperience) {
    body = (
      <ExperienceEditor
        initial={experience}
        firstRun={firstRun}
        onSave={saveExperience}
        onDismiss={firstRun ? () => void saveExperience('home_cook', '') : () => setEditingExperience(false)}
      />
    )
  } else if (exhausted || quotaError) {
    const supporter = quota?.supporter ?? chef.error?.supporter ?? false
    const resetsAt = quota?.resets_at ?? chef.error?.resetsAt
    body = supporter ? (
      <Notice title="That's your lot for now">
        You've used your supporter questions for this {quota?.month && quota.month.used >= quota.month.limit ? 'month' : 'day'}.
        Back {resetsAt ? formatReset(resetsAt) : 'soon'}.
      </Notice>
    ) : (
      <Notice title={`You've used today's ${quota?.day.limit ?? chef.status?.quotas.free ?? 5} free questions`}>
        <p>
          Supporters get {chef.status?.quotas.supporter ?? 50} a day. It also keeps the recipes coming.
        </p>
        <Link
          to="/support/"
          className="mt-3 inline-flex rounded-xl bg-cta px-5 py-2.5 text-sm font-semibold text-cta-content shadow-sm hover:bg-cta-hover transition-colors"
        >
          Become a supporter
        </Link>
        <p className="mt-3 text-xs">
          Already a supporter with another email?{' '}
          <Link to="/support/link/" className="underline hover:text-content-body">
            Link that donation
          </Link>
          . Free questions reset {resetsAt ? formatReset(resetsAt) : 'tomorrow'}.
        </p>
      </Notice>
    )
  } else {
    body = (
      <div className="flex flex-col gap-4">
        {chef.messages.length === 0 ? (
          <>
            <p className="text-sm text-content-body">
              {returning ? 'Welcome back' : 'Welcome'}
              {firstName ? `, ${firstName}` : ''}. Ask me anything about {recipe.title} — or start with one of these.
            </p>
            <ExampleQuestions recipe={recipe} servings={servings} onPick={(q) => void chef.send(q)} />
          </>
        ) : (
          <MessageList
            messages={chef.messages}
            onRate={(id, rating) => void chef.sendFeedback(id, rating)}
            onClarify={(questions, answers) => void chef.answerClarification(questions, answers)}
            activity={chef.activity}
          />
        )}
        {chef.error && chef.error.code !== 'refused' && (
          <div className="rounded-lg border border-danger-border bg-danger-surface px-3 py-2 text-sm text-danger" role="alert">
            {chef.error.message}
          </div>
        )}
      </div>
    )
  }

  const showComposer = !!user && !meLoading && chef.status?.configured && !chef.status.paused && !firstRun && !editingExperience && !exhausted && !quotaError && !signInNeeded

  return (
    <div className="fixed inset-0 z-50" data-testid="sous-chef-drawer">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="sous-chef-title"
        className="absolute inset-x-0 bottom-0 flex max-h-[85vh] flex-col rounded-t-3xl border-t border-card-border bg-card shadow-2xl md:inset-y-0 md:left-auto md:right-0 md:w-[26rem] md:max-h-none md:rounded-none md:border-l md:border-t-0"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-card-border px-5 py-4">
          <div className="min-w-0">
            <h2 id="sous-chef-title" className="font-display text-xl font-bold text-content">
              Sous Chef
            </h2>
            <p className="truncate text-xs text-content-muted">Ask about {recipe.title}</p>
            {user && experience && !firstRun && (
              <p className="mt-1 text-xs text-content-muted">
                Cooking as <span className="font-medium text-content-body">{levelLabel}</span>
                {' · '}
                <button type="button" onClick={() => setEditingExperience(true)} className="underline hover:text-brand">
                  edit
                </button>
              </p>
            )}
            {user && quota && !firstRun && (
              <div className="mt-1.5">
                <QuotaBadge quota={quota} />
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close Sous Chef"
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-card-muted text-content-muted transition-colors hover:text-content"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">{body}</div>

        {/* Composer + footer */}
        <div className="border-t border-card-border px-5 py-3">
          {showComposer && (
            <div className="mb-2">
              <Composer
                disabled={chef.phase === 'streaming'}
                streaming={chef.phase === 'streaming'}
                onSend={(q) => void chef.send(q)}
                onStop={chef.stop}
                restoreText={chef.rejectedText}
                onRestored={chef.clearRejectedText}
              />
            </div>
          )}
          <p className="text-[11px] leading-snug text-content-muted">
            Sous Chef can make mistakes. Use a thermometer and check labels.
            {user && (
              <>
                {' · '}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="!px-1 !py-0 text-[11px]"
                  onClick={deleteMyData}
                  loading={deleting}
                >
                  Delete my Sous Chef data
                </Button>
              </>
            )}
          </p>
        </div>
      </div>
    </div>
  )
}
