import { useState } from 'react'
import { Link } from 'react-router-dom'
import type { Recipe } from '../../lib/types'

function IngredientList({
  ingredients,
  checked,
  scale,
  onToggle,
}: {
  ingredients: Recipe['ingredients']
  checked: Set<number>
  scale: number
  onToggle: (i: number) => void
}) {
  // Group consecutive ingredients by their group field
  const groups: { label: string | null; items: { ing: typeof ingredients[0]; index: number }[] }[] = []
  for (let i = 0; i < ingredients.length; i++) {
    const ing = ingredients[i]
    const label = ing.group ?? null
    const last = groups[groups.length - 1]
    if (last && last.label === label) {
      last.items.push({ ing, index: i })
    } else {
      groups.push({ label, items: [{ ing, index: i }] })
    }
  }

  return (
    <div className="mt-6 space-y-4">
      {groups.map((group, gi) => (
        <div key={gi}>
          {group.label && (
            <p className="mb-2 text-xs font-bold uppercase tracking-widest text-gray-400">
              {group.label}
            </p>
          )}
          <ul className="space-y-1">
            {group.items.map(({ ing, index: i }) => (
              <li
                key={i}
                onClick={() => onToggle(i)}
                className="flex cursor-pointer items-start gap-3 rounded-xl px-2 py-3 transition-colors hover:bg-white/60 border-b border-white/40 last:border-0"
              >
                <div className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2 transition-all ${
                  checked.has(i)
                    ? 'border-primary-500 bg-primary-500 text-white'
                    : 'border-gray-300 bg-white'
                }`}>
                  {checked.has(i) && (
                    <svg className="h-3 w-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                    </svg>
                  )}
                </div>
                <span className={`leading-tight transition-all ${checked.has(i) ? 'line-through text-gray-400' : 'text-gray-700'}`}>
                  {ing.amount && <strong className={`font-bold ${checked.has(i) ? 'text-gray-400' : 'text-gray-900'}`}>{formatAmount(ing.amount, scale)} </strong>}
                  {ing.unit && <span className="font-medium">{ing.unit} </span>}
                  {ing.item}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  )
}
import { DifficultyBadge } from './DifficultyBadge'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import { CookingMode } from './CookingMode'
import { NutritionCard } from './NutritionCard'

const PLACEHOLDER =
  "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='400' viewBox='0 0 800 400'%3E%3Crect width='800' height='400' fill='%23faedcd'/%3E%3Ctext x='50%25' y='50%25' dominant-baseline='middle' text-anchor='middle' font-size='80' fill='%23e85d04'%3E%F0%9F%8D%BD%EF%B8%8F%3C/text%3E%3C/svg%3E"

function formatAmount(amount: string, scale: number): string {
  if (!amount) return ''
  const num = parseFloat(amount)
  if (isNaN(num)) return amount
  
  const scaled = num * scale
  // Smart formatting: if it's an integer, show as integer, otherwise up to 2 decimal places
  return Number.isInteger(scaled) ? scaled.toString() : scaled.toFixed(2).replace(/\.?0+$/, '')
}

export function RecipeDetail({ recipe }: { recipe: Recipe }) {
  const [servings, setServings] = useState(recipe.servings)
  const [copied, setCopied] = useState(false)
  const [cookingMode, setCookingMode] = useState(false)
  const [checked, setChecked] = useState<Set<number>>(() => {
    try {
      return new Set<number>(JSON.parse(localStorage.getItem(`grocery-${recipe.slug}`) ?? '[]'))
    } catch {
      return new Set<number>()
    }
  })
  const scale = servings / recipe.servings

  function toggleIngredient(i: number) {
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      localStorage.setItem(`grocery-${recipe.slug}`, JSON.stringify([...next]))
      return next
    })
  }

  function clearGroceryList() {
    setChecked(new Set())
    localStorage.removeItem(`grocery-${recipe.slug}`)
  }

  const handleCopyLink = () => {
    navigator.clipboard.writeText(window.location.href)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleWhatsAppShare = () => {
    const text = `Check out this recipe: ${recipe.title} - ${window.location.href}`
    window.open(`https://wa.me/?text=${encodeURIComponent(text)}`, '_blank')
  }

  const handleLinkedInShare = () => {
    const url = encodeURIComponent(window.location.href)
    window.open(`https://www.linkedin.com/sharing/share-offsite/?url=${url}`, '_blank')
  }

  const handleTwitterShare = () => {
    const text = `Check out this recipe: ${recipe.title}`
    const url = encodeURIComponent(window.location.href)
    window.open(`https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}&url=${url}`, '_blank')
  }

  const handleNativeShare = () => {
    if (navigator.share) {
      navigator.share({
        title: recipe.title,
        text: recipe.description,
        url: window.location.href,
      })
    }
  }

  return (
    <>
    <article className="mx-auto max-w-4xl px-4 py-8 md:py-12">
      {/* Hero image */}
      <div className="group relative mb-8 overflow-hidden rounded-3xl shadow-2xl">
        <img
          src={recipe.image_url ?? PLACEHOLDER}
          alt={recipe.title}
          onError={(e) => { e.currentTarget.src = PLACEHOLDER }}
          className="h-72 w-full object-cover transition-transform duration-700 group-hover:scale-105 md:h-[450px]"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-black/20 to-transparent" />
      </div>

      <div className="flex flex-col gap-8 md:flex-row md:items-start md:justify-between">
        <div className="flex-1">
          {/* Categories */}
          {recipe.categories.length > 0 && (
            <div className="mb-4 flex flex-wrap gap-2">
              {recipe.categories.map((cat) => (
                <Link key={cat} to={`/recipes?category=${encodeURIComponent(cat)}`}>
                  <Badge variant="primary" className="capitalize cursor-pointer hover:bg-primary-600 hover:text-white transition-colors">
                    {cat}
                  </Badge>
                </Link>
              ))}
            </div>
          )}

          {/* Title & description */}
          <h1 className="font-display text-4xl font-bold tracking-tight text-gray-900 md:text-5xl lg:text-6xl">
            {recipe.title}
          </h1>
          <div className="relative mt-6">
            <svg className="absolute -left-4 -top-4 h-8 w-8 text-primary-100" fill="currentColor" viewBox="0 0 24 24">
              <path d="M14.017 21L14.017 18C14.017 16.8954 14.9124 16 16.017 16H19.017C20.1216 16 21.017 16.8954 21.017 18V21C21.017 22.1046 20.1216 23 19.017 23H16.017C14.9124 23 14.017 22.1046 14.017 21ZM14.017 21C14.017 19.8954 13.1216 19 12.017 19H9.017C7.91243 19 7.017 19.8954 7.017 21V23C7.017 24.1046 7.91243 25 9.017 25H12.017C13.1216 25 14.017 24.1046 14.017 21ZM5.017 21L5.017 18C5.017 16.8954 5.91243 16 7.017 16H10.017C11.1216 16 12.017 16.8954 12.017 18V21C12.017 22.1046 11.1216 23 10.017 23H7.017C5.91243 23 5.017 22.1046 5.017 21Z" className="hidden" />
              <path d="M14.417 6.67917C14.417 8.13438 13.535 9.3875 12.2433 9.94167C11.85 10.1104 11.4583 10.2229 11.0667 10.2792C11.2333 11.5312 11.95 12.5646 13.1167 13.1125L13.1167 14.4062C11.2333 13.8458 9.91667 12.1812 9.91667 10.1875C9.91667 7.74167 11.8917 5.76667 14.3375 5.76667C14.3646 5.76667 14.3917 5.76667 14.417 5.76875L14.417 6.67917ZM10.417 6.67917C10.417 8.13438 9.535 9.3875 8.24333 9.94167C7.85 10.1104 7.45833 10.2229 7.06667 10.2792C7.23333 11.5312 7.95 12.5646 9.11667 13.1125L9.11667 14.4062C7.23333 13.8458 5.91667 12.1812 5.91667 10.1875C5.91667 7.74167 7.89167 5.76667 10.3375 5.76667C10.3646 5.76667 10.3917 5.76667 10.417 5.76875L10.417 6.67917Z" scale="2" transform="scale(3) translate(-4, -4)" />
            </svg>
            <p className="italic text-gray-600 md:text-xl leading-relaxed pl-6 border-l-4 border-primary-100">
              {recipe.description}
            </p>
          </div>
        </div>

        {/* Share buttons */}
        <div className="flex shrink-0 flex-col items-center gap-4 md:items-end">
          <div className="flex flex-col gap-2 w-full md:w-auto">
            <span className="text-center text-xs font-bold uppercase tracking-widest text-gray-400 md:text-right">
              Share Recipe
            </span>
            <div className="flex flex-wrap justify-center gap-2 md:justify-end">
              {/* LinkedIn */}
              <button 
                onClick={handleLinkedInShare}
                className="group flex h-10 items-center gap-2 rounded-xl bg-[#0077b5] pl-3 pr-4 text-xs font-bold text-white shadow-sm transition-all hover:bg-[#005582] hover:shadow-md active:scale-95"
              >
                <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M19 0h-14c-2.761 0-5 2.239-5 5v14c0 2.761 2.239 5 5 5h14c2.762 0 5-2.239 5-5v-14c0-2.761-2.238-5-5-5zm-11 19h-3v-11h3v11zm-1.5-12.268c-.966 0-1.75-.79-1.75-1.764s.784-1.764 1.75-1.764 1.75.79 1.75 1.764-.783 1.764-1.75 1.764zm13.5 12.268h-3v-5.604c0-3.368-4-3.113-4 0v5.604h-3v-11h3v1.765c1.396-2.586 7-2.777 7 2.476v6.759z" />
                </svg>
                LinkedIn
              </button>

              {/* Twitter / X */}
              <button 
                onClick={handleTwitterShare}
                className="group flex h-10 items-center gap-2 rounded-xl bg-black pl-3 pr-4 text-xs font-bold text-white shadow-sm transition-all hover:bg-gray-800 hover:shadow-md active:scale-95"
              >
                <svg className="h-3.5 w-3.5" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M18.244 2.25h3.308l-7.227 8.26 8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z" />
                </svg>
                Post
              </button>

              {/* WhatsApp */}
              <button 
                onClick={handleWhatsAppShare}
                className="group flex h-10 items-center gap-2 rounded-xl bg-[#25D366] pl-3 pr-4 text-xs font-bold text-white shadow-sm transition-all hover:bg-[#128C7E] hover:shadow-md active:scale-95"
              >
                <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413Z" />
                </svg>
                Send
              </button>
            </div>
          </div>

          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={handleCopyLink} className="h-10 gap-2 rounded-xl border border-gray-100 bg-white px-4 shadow-sm hover:bg-gray-50">
              <svg className="h-4 w-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 5H6a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2v-1M8 5a2 2 0 002 2h2a2 2 0 002-2M8 5a2 2 0 012-2h2a2 2 0 012 2m0 0h2a2 2 0 012 2v3m2 4H10m0 0l3-3m-3 3l3 3" />
              </svg>
              {copied ? 'Copied!' : 'Copy Link'}
            </Button>

            {'share' in navigator && (
              <Button variant="ghost" size="sm" onClick={handleNativeShare} className="h-10 gap-2 rounded-xl border border-gray-100 bg-white px-4 shadow-sm hover:bg-gray-50">
                <svg className="h-4 w-4 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.684 13.342C8.886 12.938 9 12.482 9 12c0-.482-.114-.938-.316-1.342m0 2.684a3 3 0 110-2.684m0 2.684l6.632 3.316m-6.632-6l6.632-3.316m0 0a3 3 0 105.367-2.684 3 3 0 00-5.367 2.684zm0 9.316a3 3 0 105.368 2.684 3 3 0 00-5.368-2.684z" />
                </svg>
                More
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Metadata bar */}
      <div className="mt-10 grid grid-cols-2 gap-4 rounded-3xl bg-surface-dark p-6 sm:grid-cols-4 md:p-8">
        <MetaItem 
          label="Prep time" 
          value={`${recipe.prep_time_minutes}m`} 
          icon={<svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" /></svg>}
        />
        <MetaItem 
          label="Cook time" 
          value={`${recipe.cook_time_minutes}m`} 
          icon={<svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" /></svg>}
        />
        <MetaItem 
          label="Servings" 
          value={
            <div className="flex items-center gap-2">
              <button 
                onClick={() => setServings(Math.max(1, servings - 1))}
                className="flex h-6 w-6 items-center justify-center rounded-full bg-white text-gray-500 shadow-sm transition-colors hover:bg-primary-600 hover:text-white"
              >
                -
              </button>
              <span className="min-w-[1.5rem] text-center">{servings}</span>
              <button 
                onClick={() => setServings(servings + 1)}
                className="flex h-6 w-6 items-center justify-center rounded-full bg-white text-gray-500 shadow-sm transition-colors hover:bg-primary-600 hover:text-white"
              >
                +
              </button>
            </div>
          }
          icon={<svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" /></svg>}
        />
        <div className="flex flex-col gap-2">
          <span className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest text-gray-400">
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" /></svg>
            Difficulty
          </span>
          <DifficultyBadge difficulty={recipe.difficulty} className="w-fit" />
        </div>
      </div>

      {/* Start Cooking button */}
      <div className="mt-6 flex justify-center md:justify-start">
        <button
          onClick={() => setCookingMode(true)}
          className="inline-flex items-center gap-2 rounded-2xl bg-primary-600 px-8 py-4 text-base font-semibold text-white shadow-lg shadow-primary-200 transition-all hover:bg-primary-700 hover:shadow-xl active:scale-95"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          Start Cooking
        </button>
      </div>

      {/* Ingredients + Instructions */}
      <div className="mt-12 grid gap-12 lg:grid-cols-3">
        {/* Ingredients */}
        <section className="rounded-3xl bg-surface-dark p-8">
          <div className="flex items-center justify-between">
            <h2 className="font-display text-2xl font-bold text-gray-900 underline decoration-primary-200 decoration-4 underline-offset-8">
              Grocery List
            </h2>
            {checked.size > 0 && (
              <button
                onClick={clearGroceryList}
                className="text-xs font-medium text-gray-400 hover:text-red-500 transition-colors"
              >
                Clear all
              </button>
            )}
          </div>
          {/* Progress */}
          <div className="mt-4">
            <div className="flex items-center justify-between text-xs text-gray-400 mb-1.5">
              <span>
                {checked.size === recipe.ingredients.length
                  ? 'All ready to cook!'
                  : `${checked.size} of ${recipe.ingredients.length} checked`}
              </span>
            </div>
            <div className="h-1.5 w-full rounded-full bg-white/60">
              <div
                className="h-full rounded-full bg-primary-500 transition-all duration-300"
                style={{ width: `${(checked.size / recipe.ingredients.length) * 100}%` }}
              />
            </div>
          </div>
          <IngredientList
            ingredients={recipe.ingredients}
            checked={checked}
            scale={scale}
            onToggle={toggleIngredient}
          />
        </section>

        {/* Instructions */}
        <section className="lg:col-span-2">
          <h2 className="font-display text-2xl font-bold text-gray-900 underline decoration-primary-200 decoration-4 underline-offset-8">
            Instructions
          </h2>
          <ol className="mt-8 space-y-8">
            {recipe.instructions.map((inst) => (
              <li key={inst.step} className="group flex gap-6">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-white border border-gray-100 font-display text-lg font-bold text-primary-600 shadow-sm transition-all group-hover:bg-primary-600 group-hover:text-white">
                  {inst.step}
                </span>
                <div className="pt-1.5 flex flex-col gap-3">
                  <p className="text-lg leading-relaxed text-gray-700">{inst.text}</p>
                  {inst.tip && (
                    <div className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3">
                      <span className="text-base leading-none mt-0.5">💡</span>
                      <p className="text-sm leading-relaxed text-amber-800">{inst.tip}</p>
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>
      </div>
      <NutritionCard nutrition={recipe.nutrition} scale={scale} />
    </article>

    {/* Cooking Mode overlay */}
    {cookingMode && (
      <CookingMode recipe={recipe} onExit={() => setCookingMode(false)} />
    )}
  </>
  )
}

function MetaItem({ label, value, icon }: { label: string; value: React.ReactNode; icon: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <span className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-widest text-gray-400">
        <span className="text-primary-500/60">{icon}</span>
        {label}
      </span>
      <span className="text-lg font-bold text-gray-900">{value}</span>
    </div>
  )
}
