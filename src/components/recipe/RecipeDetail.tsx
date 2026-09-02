import { lazy, Suspense, useState } from 'react'
import { Link } from 'react-router-dom'
import type { Recipe, RecipeComponent, Ingredient } from '../../lib/types'
import { DifficultyBadge } from './DifficultyBadge'
import { Badge } from '../ui/Badge'
import { CookingMode } from './CookingMode'
import { NutritionCard } from './NutritionCard'
import { formatIngredient, type UnitSystem } from '../../lib/units'
import { safeImageUrl } from '../../lib/safe-url'

// The Sous Chef drawer (and its streaming client) only loads on first click,
// the same policy as the admin pages: public visitors never pay for it.
const SousChefDrawer = lazy(() =>
  import('../assistant/SousChefDrawer').then((m) => ({ default: m.SousChefDrawer }))
)

const PLACEHOLDER =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='400' viewBox='0 0 800 400'%3E%3Crect width='800' height='400' fill='%23faedcd'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-size='80' fill='%23e85d04'%3E%F0%9F%8D%BD%EF%B8%8F%3C/text%3E%3C/svg%3E"

// ─── Ingredient list ──────────────────────────────────────────────────────────

function IngredientList({
  ingredients,
  checked,
  scale,
  system,
  onToggle,
  keyPrefix = 'root',
}: {
  ingredients: Ingredient[]
  checked: Set<string>
  scale: number
  system: UnitSystem
  onToggle: (key: string) => void
  keyPrefix?: string
}) {
  const groups: { label: string | null; items: { ing: Ingredient; key: string }[] }[] = []
  for (let i = 0; i < ingredients.length; i++) {
    const ing = ingredients[i]
    const label = ing.group ?? null
    const key = `${keyPrefix}-${i}`
    const last = groups[groups.length - 1]
    if (last && last.label === label) {
      last.items.push({ ing, key })
    } else {
      groups.push({ label, items: [{ ing, key }] })
    }
  }

  return (
    <div className="mt-6 space-y-4">
      {groups.map((group, gi) => (
        <div key={gi}>
          {group.label && (
            <p className="mb-2 text-xs font-bold uppercase tracking-widest text-content-muted">
              {group.label}
            </p>
          )}
          <ul className="space-y-1">
            {group.items.map(({ ing, key }) => {
              const { amount: displayAmt, unit: displayUnit } = formatIngredient(
                ing.amount ?? '',
                ing.unit,
                scale,
                system,
              )
              const isChecked = checked.has(key)
              return (
                <li
                  key={key}
                  onClick={() => onToggle(key)}
                  className="flex cursor-pointer items-start gap-3 rounded-xl border-b border-card-border px-2 py-3 transition-colors last:border-0 hover:bg-control-hover"
                >
                  <div
                    className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-all ${
                      isChecked
                        ? 'border-primary-500 bg-primary-500 text-on-brand'
                        : 'border-control-border bg-control'
                    }`}
                  >
                    {isChecked && (
                      <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                      </svg>
                    )}
                  </div>
                  <span
                    className={`leading-tight transition-all ${
                      isChecked
                        ? 'line-through text-content-muted opacity-70'
                        : 'text-content-body'
                    }`}
                  >
                    {displayAmt && (
                      <strong
                        className={`font-bold ${isChecked ? 'text-content-muted' : 'text-content'}`}
                      >
                        {displayAmt}{' '}
                      </strong>
                    )}
                    {displayUnit && <span className="font-medium">{displayUnit} </span>}
                    {ing.item}
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </div>
  )
}

// ─── Multi-component helpers ──────────────────────────────────────────────────

function ComponentTimingBar({ comp }: { comp: RecipeComponent }) {
  const items: { label: string; value: string }[] = []
  if (comp.prep_time_minutes) items.push({ label: 'Prep', value: `${comp.prep_time_minutes}m` })
  if (comp.cook_time_minutes) items.push({ label: 'Cook', value: `${comp.cook_time_minutes}m` })
  if (comp.yield_description) items.push({ label: 'Yield', value: comp.yield_description })
  if (items.length === 0) return null
  return (
    <div className="mb-6 flex flex-wrap gap-4">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-1.5 rounded-xl bg-surface-dark px-4 py-2">
          <span className="text-xs font-bold uppercase tracking-widest text-content-muted">
            {item.label}
          </span>
          <span className="text-sm font-bold text-content">{item.value}</span>
        </div>
      ))}
    </div>
  )
}

function ComponentSection({
  comp,
  index,
  checked,
  scale,
  system,
  onToggle,
}: {
  comp: RecipeComponent
  index: number
  checked: Set<string>
  scale: number
  system: UnitSystem
  onToggle: (key: string) => void
}) {
  return (
    <section id={`comp-${index}`} className="scroll-mt-20">
      <div className="mb-6 flex items-center gap-4">
        <div className="h-px flex-1 bg-card-border" />
        <h2 className="font-display text-xl font-bold text-content whitespace-nowrap">
          {comp.title}
        </h2>
        <div className="h-px flex-1 bg-card-border" />
      </div>

      {comp.description && (
        <p className="mb-6 border-l-4 border-brand-border pl-4 italic leading-relaxed text-content-muted">
          {comp.description}
        </p>
      )}

      <ComponentTimingBar comp={comp} />

      <div className="grid gap-8 lg:grid-cols-3">
        {comp.ingredients.length > 0 && (
          <div className="rounded-3xl bg-surface-dark p-6">
            <h3 className="mb-4 font-display text-lg font-bold text-content underline decoration-brand-border decoration-4 underline-offset-8">
              Ingredients
            </h3>
            <IngredientList
              ingredients={comp.ingredients}
              checked={checked}
              scale={scale}
              system={system}
              keyPrefix={`comp-${index}`}
              onToggle={onToggle}
            />
          </div>
        )}

        {(comp.prep_steps?.length ?? 0) > 0 && (
          <section className="lg:col-span-3">
            <h3 className="mb-4 font-display text-lg font-bold text-content underline decoration-brand-border decoration-4 underline-offset-8">
              Ingredient Preparation
            </h3>
            <ol className="mb-6 space-y-4">
              {comp.prep_steps!.map((inst) => (
                <li key={inst.step} className="group flex gap-4">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-card-border bg-card font-display text-sm font-bold text-content-muted shadow-sm">
                    {inst.step}
                  </span>
                  <div className="flex flex-col gap-2 pt-1">
                    <p className="leading-relaxed text-content-body">{inst.text}</p>
                    {inst.tip && (
                      <div className="flex items-start gap-2 rounded-xl border border-warning-border bg-warning-surface px-3 py-2">
                        <span className="mt-0.5 text-sm leading-none">💡</span>
                        <p className="text-xs leading-relaxed text-warning">{inst.tip}</p>
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ol>
            <div className="mb-6 h-px bg-card-border" />
          </section>
        )}

        {comp.instructions.length > 0 && (
          <section className={comp.ingredients.length > 0 ? 'lg:col-span-2' : 'lg:col-span-3'}>
            <h3 className="mb-6 font-display text-lg font-bold text-content underline decoration-brand-border decoration-4 underline-offset-8">
              Instructions
            </h3>
            <ol className="space-y-6">
              {comp.instructions.map((inst) => (
                <li key={inst.step} className="group flex gap-6">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-card-border bg-card font-display text-lg font-bold text-brand shadow-sm transition-all group-hover:border-primary-600 group-hover:bg-primary-600 group-hover:text-on-brand">
                    {inst.step}
                  </span>
                  <div className="flex flex-col gap-3 pt-1.5">
                    <p className="text-lg leading-relaxed text-content-body">{inst.text}</p>
                    {inst.tip && (
                      <div className="flex items-start gap-2 rounded-xl border border-warning-border bg-warning-surface px-4 py-3">
                        <span className="mt-0.5 text-base leading-none">💡</span>
                        <p className="text-sm leading-relaxed text-warning">{inst.tip}</p>
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        )}
      </div>
    </section>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

export function RecipeDetail({ recipe }: { recipe: Recipe }) {
  const [servings, setServings] = useState(recipe.servings)
  const [copied, setCopied] = useState(false)
  const [cookingMode, setCookingMode] = useState(false)
  const [sousChefOpen, setSousChefOpen] = useState(false)
  const [unitSystem, setUnitSystem] = useState<UnitSystem>(() => {
    const stored = localStorage.getItem('unit-system')
    return stored === 'metric' ? 'metric' : 'imperial'
  })
  const [checked, setChecked] = useState<Set<string>>(() => {
    try {
      return new Set<string>(JSON.parse(localStorage.getItem(`grocery-${recipe.slug}`) ?? '[]'))
    } catch {
      return new Set<string>()
    }
  })
  const scale = servings / recipe.servings

  const isMultiComponent = (recipe.components?.length ?? 0) > 0
  const aggregatedIngredients: Ingredient[] = isMultiComponent
    ? recipe.components!.flatMap((comp) =>
        comp.ingredients.map((ing) => ({ ...ing, group: comp.title }))
      )
    : recipe.ingredients

  const totalIngredients = aggregatedIngredients.length || recipe.ingredients.length

  function toggleIngredient(key: string) {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      localStorage.setItem(`grocery-${recipe.slug}`, JSON.stringify([...next]))
      return next
    })
  }

  function clearGroceryList() {
    setChecked(new Set())
    localStorage.removeItem(`grocery-${recipe.slug}`)
  }

  function handleSetUnitSystem(system: UnitSystem) {
    localStorage.setItem('unit-system', system)
    setUnitSystem(system)
  }

  const handleCopyLink = () => {
    navigator.clipboard.writeText(window.location.href)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const pageUrl = encodeURIComponent(window.location.href)
  const pageTitle = encodeURIComponent(`Check out this recipe: ${recipe.title}`)

  const handleFacebookShare = () =>
    window.open(`https://www.facebook.com/sharer/sharer.php?u=${pageUrl}`, '_blank')
  const handleTwitterShare = () =>
    window.open(`https://twitter.com/intent/tweet?text=${pageTitle}&url=${pageUrl}`, '_blank')
  const handleWhatsAppShare = () =>
    window.open(`https://wa.me/?text=${pageTitle}%20${pageUrl}`, '_blank')
  const handlePinterestShare = () =>
    window.open(
      `https://pinterest.com/pin/create/button/?url=${pageUrl}&description=${pageTitle}`,
      '_blank',
    )
  const handleRedditShare = () =>
    window.open(`https://reddit.com/submit?url=${pageUrl}&title=${pageTitle}`, '_blank')
  const handleTelegramShare = () =>
    window.open(`https://t.me/share/url?url=${pageUrl}&text=${pageTitle}`, '_blank')
  const handleNativeShare = () => {
    if (navigator.share) {
      navigator.share({ title: recipe.title, text: recipe.description, url: window.location.href })
    }
  }

  return (
    <>
      <article className="mx-auto max-w-4xl px-4 py-8 md:py-12">
        {/* Hero image */}
        <div className="group relative mb-8 overflow-hidden rounded-3xl shadow-2xl">
          <img
            src={safeImageUrl(recipe.image_url) ?? PLACEHOLDER}
            alt={recipe.title}
            fetchPriority="high"
            decoding="async"
            onError={(e) => {
              e.currentTarget.src = PLACEHOLDER
            }}
            className="h-72 w-full object-cover transition-transform duration-700 group-hover:scale-105 md:h-[450px]"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/20 to-transparent" />
        </div>

        <div className="flex flex-col gap-8 md:flex-row md:items-start md:justify-between">
          <div className="flex-1">
            {/* Categories */}
            {recipe.categories.length > 0 && (
              <div className="mb-3 flex flex-wrap gap-2">
                {recipe.categories.map((cat) => (
                  <Link key={cat} to={`/recipes/?category=${encodeURIComponent(cat)}`}>
                    <Badge
                      variant="primary"
                      className="capitalize cursor-pointer hover:bg-primary-600 hover:text-on-brand transition-colors"
                    >
                      {cat}
                    </Badge>
                  </Link>
                ))}
              </div>
            )}

            {/* Labels */}
            {(recipe.labels?.length ?? 0) > 0 && (
              <div className="mb-4 flex flex-wrap gap-1.5">
                {recipe.labels!.map((lbl) => (
                  <span
                    key={lbl}
                    className="rounded-full bg-badge-surface px-2.5 py-0.5 text-xs font-medium capitalize text-badge"
                  >
                    {lbl}
                  </span>
                ))}
              </div>
            )}

            {/* Title & description */}
            <h1 className="font-display text-4xl font-bold tracking-tight text-content md:text-5xl lg:text-6xl">
              {recipe.title}
            </h1>
            <div className="relative mt-6">
              <svg
                className="absolute -left-4 -top-4 h-8 w-8 text-primary-100"
                fill="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  d="M14.417 6.67917C14.417 8.13438 13.535 9.3875 12.2433 9.94167C11.85 10.1104 11.4583 10.2229 11.0667 10.2792C11.2333 11.5312 11.95 12.5646 13.1167 13.1125L13.1167 14.4062C11.2333 13.8458 9.91667 12.1812 9.91667 10.1875C9.91667 7.74167 11.8917 5.76667 14.3375 5.76667C14.3646 5.76667 14.3917 5.76667 14.417 5.76875L14.417 6.67917ZM10.417 6.67917C10.417 8.13438 9.535 9.3875 8.24333 9.94167C7.85 10.1104 7.45833 10.2229 7.06667 10.2792C7.23333 11.5312 7.95 12.5646 9.11667 13.1125L9.11667 14.4062C7.23333 13.8458 5.91667 12.1812 5.91667 10.1875C5.91667 7.74167 7.89167 5.76667 10.3375 5.76667C10.3646 5.76667 10.3917 5.76667 10.417 5.76875L10.417 6.67917Z"
                  transform="scale(3) translate(-4, -4)"
                />
              </svg>
              <p className="border-l-4 border-brand-border pl-6 italic leading-relaxed text-content-muted md:text-xl">
                {recipe.description}
              </p>
            </div>
          </div>

          {/* Share buttons */}
          <div className="no-print flex shrink-0 flex-col items-end gap-2">
            <span className="text-xs font-bold uppercase tracking-widest text-content-muted">
              Share
            </span>
            <div className="flex flex-wrap justify-end gap-1.5">
              {/* Facebook */}
              <button
                onClick={handleFacebookShare}
                title="Share on Facebook"
                className="flex h-8 w-8 items-center justify-center rounded-full bg-social-facebook text-social-facebook-content transition-all hover:opacity-85 active:scale-90"
              >
                <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M24 12.073c0-6.627-5.373-12-12-12s-12 5.373-12 12c0 5.99 4.388 10.954 10.125 11.854v-8.385H7.078v-3.47h3.047V9.43c0-3.007 1.792-4.669 4.533-4.669 1.312 0 2.686.235 2.686.235v2.953H15.83c-1.491 0-1.956.925-1.956 1.874v2.25h3.328l-.532 3.47h-2.796v8.385C19.612 23.027 24 18.062 24 12.073z" />
                </svg>
              </button>

              {/* X / Twitter */}
              <button
                onClick={handleTwitterShare}
                title="Post on X"
                className="flex h-8 w-8 items-center justify-center rounded-full bg-social-x text-social-x-content transition-all hover:opacity-75 active:scale-90"
              >
                <svg className="h-3 w-3" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                </svg>
              </button>

              {/* WhatsApp */}
              <button
                onClick={handleWhatsAppShare}
                title="Send on WhatsApp"
                className="flex h-8 w-8 items-center justify-center rounded-full bg-social-whatsapp text-social-whatsapp-content transition-all hover:opacity-85 active:scale-90"
              >
                <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z" />
                </svg>
              </button>

              {/* Pinterest */}
              <button
                onClick={handlePinterestShare}
                title="Pin on Pinterest"
                className="flex h-8 w-8 items-center justify-center rounded-full bg-social-pinterest text-social-pinterest-content transition-all hover:opacity-85 active:scale-90"
              >
                <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 0C5.373 0 0 5.373 0 12c0 5.084 3.163 9.426 7.627 11.174-.105-.949-.2-2.405.042-3.441.218-.937 1.407-5.965 1.407-5.965s-.359-.719-.359-1.782c0-1.668.967-2.914 2.171-2.914 1.023 0 1.518.769 1.518 1.69 0 1.029-.655 2.568-.994 3.995-.283 1.194.599 2.169 1.777 2.169 2.133 0 3.772-2.249 3.772-5.495 0-2.873-2.064-4.882-5.012-4.882-3.414 0-5.418 2.561-5.418 5.207 0 1.031.397 2.138.893 2.738a.36.36 0 01.083.345l-.333 1.36c-.053.22-.174.267-.402.161-1.499-.698-2.436-2.889-2.436-4.649 0-3.785 2.75-7.262 7.929-7.262 4.163 0 7.398 2.967 7.398 6.931 0 4.136-2.607 7.464-6.227 7.464-1.216 0-2.359-.632-2.75-1.378l-.748 2.853c-.271 1.043-1.002 2.35-1.492 3.146C9.57 23.812 10.763 24 12 24c6.627 0 12-5.373 12-12S18.627 0 12 0z" />
                </svg>
              </button>

              {/* Reddit */}
              <button
                onClick={handleRedditShare}
                title="Share on Reddit"
                className="flex h-8 w-8 items-center justify-center rounded-full bg-social-reddit text-social-reddit-content transition-all hover:opacity-85 active:scale-90"
              >
                <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0zm5.01 4.744c.688 0 1.25.561 1.25 1.249a1.25 1.25 0 0 1-2.498.056l-2.597-.547-.8 3.747c1.824.07 3.48.632 4.674 1.488.308-.309.73-.491 1.207-.491.968 0 1.754.786 1.754 1.754 0 .716-.435 1.333-1.01 1.614a3.111 3.111 0 0 1 .042.52c0 2.694-3.13 4.87-7.004 4.87-3.874 0-7.004-2.176-7.004-4.87 0-.183.015-.366.043-.534A1.748 1.748 0 0 1 4.028 12c0-.968.786-1.754 1.754-1.754.463 0 .898.196 1.207.49 1.207-.883 2.878-1.43 4.744-1.487l.885-4.182a.342.342 0 0 1 .14-.197.35.35 0 0 1 .238-.042l2.906.617a1.214 1.214 0 0 1 1.108-.701zM9.25 12C8.561 12 8 12.562 8 13.25c0 .687.561 1.248 1.25 1.248.687 0 1.248-.561 1.248-1.249 0-.688-.561-1.249-1.249-1.249zm5.5 0c-.687 0-1.248.561-1.248 1.25 0 .687.561 1.248 1.249 1.248.688 0 1.249-.561 1.249-1.249 0-.687-.562-1.249-1.25-1.249zm-5.466 3.99a.327.327 0 0 0-.231.094.33.33 0 0 0 0 .463c.842.842 2.484.913 2.961.913.477 0 2.105-.056 2.961-.913a.361.361 0 0 0 .029-.463.33.33 0 0 0-.464 0c-.547.533-1.684.73-2.512.73-.828 0-1.979-.196-2.512-.73a.326.326 0 0 0-.232-.095z" />
                </svg>
              </button>

              {/* Telegram */}
              <button
                onClick={handleTelegramShare}
                title="Share on Telegram"
                className="flex h-8 w-8 items-center justify-center rounded-full bg-social-telegram text-social-telegram-content transition-all hover:opacity-85 active:scale-90"
              >
                <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z" />
                </svg>
              </button>

              {/* Copy link */}
              <button
                onClick={handleCopyLink}
                title="Copy link"
                className={`flex h-8 w-8 items-center justify-center rounded-full transition-all active:scale-90 ${
                  copied
                    ? 'bg-success-fill text-success-content'
                    : 'bg-control-hover text-content-body hover:bg-card-border'
                }`}
              >
                {copied ? (
                  <svg
                    className="h-3.5 w-3.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2.5}
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  <svg
                    className="h-3.5 w-3.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
                    />
                  </svg>
                )}
              </button>

              {/* Native share (mobile) */}
              {'share' in navigator && (
                <button
                  onClick={handleNativeShare}
                  title="More ways to share"
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-control-hover text-content-body transition-all hover:bg-card-border active:scale-90"
                >
                  <svg
                    className="h-3.5 w-3.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z"
                    />
                  </svg>
                </button>
              )}
            </div>
          </div>
        </div>

        {/* About this dish */}
        {recipe.about && (
          <div className="mt-8 rounded-3xl border border-brand-border border-l-4 bg-brand-surface px-6 py-5">
            <h2 className="mb-2 text-xs font-bold uppercase tracking-widest text-brand">
              About this dish
            </h2>
            <p className="text-base italic leading-relaxed text-content-body">
              {recipe.about}
            </p>
          </div>
        )}

        {/* Metadata bar */}
        <div className="mt-10 grid grid-cols-2 gap-4 rounded-3xl bg-surface-dark p-6 sm:grid-cols-4 md:p-8">
          <MetaItem
            label="Prep time"
            value={`${recipe.prep_time_minutes}m`}
            icon={
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
            }
          />
          <MetaItem
            label="Cook time"
            value={`${recipe.cook_time_minutes}m`}
            icon={
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
            }
          />
          <MetaItem
            label="Servings"
            value={
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setServings(Math.max(1, servings - 1))}
                  className="no-print flex h-6 w-6 items-center justify-center rounded-full border border-card-border bg-card text-content-muted shadow-sm transition-colors hover:border-primary-600 hover:bg-primary-600 hover:text-on-brand"
                >
                  -
                </button>
                <span className="min-w-[1.5rem] text-center">{servings}</span>
                <button
                  onClick={() => setServings(servings + 1)}
                  className="no-print flex h-6 w-6 items-center justify-center rounded-full border border-card-border bg-card text-content-muted shadow-sm transition-colors hover:border-primary-600 hover:bg-primary-600 hover:text-on-brand"
                >
                  +
                </button>
              </div>
            }
            icon={
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z"
                />
              </svg>
            }
          />
          <div className="flex flex-col gap-2">
            <span className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest text-content-muted">
              <span className="text-brand">
                <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"
                  />
                </svg>
              </span>
              Difficulty
            </span>
            <DifficultyBadge difficulty={recipe.difficulty} className="w-fit" />
          </div>
        </div>

        {/* Action buttons */}
        <div className="no-print mt-6 flex flex-wrap items-center justify-center gap-3 md:justify-start">
          <button
            onClick={() => setCookingMode(true)}
            className="inline-flex items-center gap-2 rounded-2xl bg-primary-600 px-8 py-4 text-base font-semibold text-on-brand shadow-lg transition-all hover:bg-primary-500 hover:shadow-xl active:scale-95"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            Start Cooking
          </button>
          <button
            onClick={() => window.print()}
            className="inline-flex items-center gap-2 rounded-2xl border border-control-border bg-control px-6 py-4 text-base font-medium text-content-body transition-all hover:border-brand-border hover:text-brand hover:shadow-md active:scale-95"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4a2 2 0 00-2-2H9a2 2 0 00-2 2v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z"
              />
            </svg>
            Print Recipe
          </button>
          <button
            onClick={() => setSousChefOpen(true)}
            className="inline-flex items-center gap-2 rounded-2xl border border-control-border bg-control px-6 py-4 text-base font-medium text-content-body transition-all hover:border-brand-border hover:text-brand hover:shadow-md active:scale-95"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-4 4v-4z"
              />
            </svg>
            Ask the Sous Chef
          </button>
        </div>

        {/* Multi-component jump nav */}
        {isMultiComponent && (
          <nav className="no-print sticky top-16 z-30 mt-8 -mx-4 flex gap-1 overflow-x-auto border-y border-card-border bg-card/95 backdrop-blur-sm px-4 py-2">
            {recipe.components!.map((comp, i) => (
              <a
                key={i}
                href={`#comp-${i}`}
                className="shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium text-content-muted transition-colors hover:bg-brand-surface hover:text-brand"
              >
                {comp.title}
              </a>
            ))}
          </nav>
        )}

        {/* Grocery list + instructions */}
        <div className="mt-12 grid gap-12 lg:grid-cols-3">
          <section className="rounded-3xl bg-surface-dark p-8">
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-display text-2xl font-bold text-content underline decoration-brand-border decoration-4 underline-offset-8">
                Grocery List
              </h2>
              <div className="no-print flex items-center gap-2">
                {/* Unit system toggle */}
                <div className="flex overflow-hidden rounded-lg border border-card-border text-xs">
                  <button
                    onClick={() => handleSetUnitSystem('imperial')}
                    className={`px-2 py-1 transition-colors ${
                      unitSystem === 'imperial'
                        ? 'bg-brand-surface font-medium text-brand'
                        : 'text-content-muted hover:bg-control-hover hover:text-content-body'
                    }`}
                    title="Imperial (oz, cups, lb)"
                    aria-pressed={unitSystem === 'imperial'}
                  >
                    US
                  </button>
                  <button
                    onClick={() => handleSetUnitSystem('metric')}
                    className={`px-2 py-1 transition-colors ${
                      unitSystem === 'metric'
                        ? 'bg-brand-surface font-medium text-brand'
                        : 'text-content-muted hover:bg-control-hover hover:text-content-body'
                    }`}
                    title="Metric (g, ml)"
                    aria-pressed={unitSystem === 'metric'}
                  >
                    Metric
                  </button>
                </div>
                {checked.size > 0 && (
                  <button
                    onClick={clearGroceryList}
                    className="text-xs font-medium text-content-muted transition-colors hover:text-danger"
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>

            {/* Progress bar */}
            <div className="no-print mt-4">
              <div className="mb-1.5 flex items-center justify-between text-xs text-content-muted">
                <span>
                  {checked.size === totalIngredients
                    ? 'All ready to cook!'
                    : `${checked.size} of ${totalIngredients} checked`}
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-card-border">
                <div
                  className="h-full rounded-full bg-primary-500 transition-all duration-300"
                  style={{
                    width: `${totalIngredients > 0 ? (checked.size / totalIngredients) * 100 : 0}%`,
                  }}
                />
              </div>
            </div>

            <IngredientList
              ingredients={aggregatedIngredients}
              checked={checked}
              scale={scale}
              system={unitSystem}
              keyPrefix="grocery"
              onToggle={toggleIngredient}
            />
          </section>

          {/* Single-component instructions */}
          {!isMultiComponent && (
            <section className="lg:col-span-2">
              {(recipe.prep_steps?.length ?? 0) > 0 && (
                <>
                  <h2 className="font-display text-2xl font-bold text-content underline decoration-brand-border decoration-4 underline-offset-8">
                    Ingredient Preparation
                  </h2>
                  <ol className="mb-12 mt-8 space-y-8">
                    {recipe.prep_steps!.map((inst) => (
                      <li key={inst.step} className="group flex gap-6">
                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-card-border bg-card font-display text-lg font-bold text-content-muted shadow-sm transition-all group-hover:bg-neutral group-hover:text-neutral-content">
                          {inst.step}
                        </span>
                        <div className="flex flex-col gap-3 pt-1.5">
                          <p className="text-lg leading-relaxed text-content-body">
                            {inst.text}
                          </p>
                          {inst.tip && (
                            <div className="flex items-start gap-2 rounded-xl border border-warning-border bg-warning-surface px-4 py-3">
                              <span className="mt-0.5 text-base leading-none">💡</span>
                              <p className="text-sm leading-relaxed text-warning">
                                {inst.tip}
                              </p>
                            </div>
                          )}
                        </div>
                      </li>
                    ))}
                  </ol>
                  <div className="mb-8 h-px bg-card-border" />
                </>
              )}

              <h2 className="font-display text-2xl font-bold text-content underline decoration-brand-border decoration-4 underline-offset-8">
                Instructions
              </h2>
              <ol className="mt-8 space-y-8">
                {recipe.instructions.map((inst) => (
                  <li key={inst.step} className="group flex gap-6">
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-card-border bg-card font-display text-lg font-bold text-brand shadow-sm transition-all group-hover:border-primary-600 group-hover:bg-primary-600 group-hover:text-on-brand">
                      {inst.step}
                    </span>
                    <div className="flex flex-col gap-3 pt-1.5">
                      <p className="text-lg leading-relaxed text-content-body">
                        {inst.text}
                      </p>
                      {inst.tip && (
                        <div className="flex items-start gap-2 rounded-xl border border-warning-border bg-warning-surface px-4 py-3">
                          <span className="mt-0.5 text-base leading-none">💡</span>
                          <p className="text-sm leading-relaxed text-warning">
                            {inst.tip}
                          </p>
                        </div>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>

        {/* Multi-component sections */}
        {isMultiComponent && (
          <div className="mt-12 flex flex-col gap-16">
            {recipe.components!.map((comp, i) => (
              <ComponentSection
                key={i}
                comp={comp}
                index={i}
                checked={checked}
                scale={scale}
                system={unitSystem}
                onToggle={toggleIngredient}
              />
            ))}
          </div>
        )}

        {/* Chef's secrets */}
        {(recipe.secrets?.length ?? 0) > 0 && (
          <div className="mt-12">
            <h2 className="mb-6 font-display text-2xl font-bold text-content underline decoration-brand-border decoration-4 underline-offset-8">
              Chef's Secrets
            </h2>
            <div className="grid gap-4 sm:grid-cols-2">
              {recipe.secrets!.map((secret, i) => (
                <div
                  key={i}
                  className="rounded-3xl border border-brand-border bg-brand-surface p-6"
                >
                  <h3 className="mb-2 font-display text-lg font-bold text-content">
                    {secret.title}
                  </h3>
                  <p className="text-sm leading-relaxed text-content-muted">
                    {secret.body}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        <NutritionCard nutrition={recipe.nutrition} scale={scale} />
      </article>

      {/* Cooking Mode overlay — flatten multi-component instructions */}
      {cookingMode && (
        <CookingMode
          recipe={
            isMultiComponent
              ? {
                  ...recipe,
                  instructions: recipe.components!.flatMap((comp, ci) =>
                    comp.instructions.map((inst, ii) => ({
                      ...inst,
                      step:
                        recipe.components!
                          .slice(0, ci)
                          .reduce((acc, c) => acc + c.instructions.length, 0) +
                        ii +
                        1,
                      tip:
                        ii === 0
                          ? `── ${comp.title} ──${inst.tip ? `\n💡 ${inst.tip}` : ''}`
                          : inst.tip,
                    })),
                  ),
                }
              : recipe
          }
          onExit={() => setCookingMode(false)}
        />
      )}

      {/* Sous Chef drawer — sees the same servings/unit system the reader does */}
      {sousChefOpen && (
        <Suspense fallback={null}>
          <SousChefDrawer
            recipe={recipe}
            servings={servings}
            unitSystem={unitSystem}
            onClose={() => setSousChefOpen(false)}
          />
        </Suspense>
      )}
    </>
  )
}

function MetaItem({
  label,
  value,
  icon,
}: {
  label: string
  value: React.ReactNode
  icon: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-2">
      <span className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest text-content-muted">
        <span className="text-brand">{icon}</span>
        {label}
      </span>
      <div className="text-lg font-bold text-content">{value}</div>
    </div>
  )
}
