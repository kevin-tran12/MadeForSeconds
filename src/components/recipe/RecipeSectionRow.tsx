import { useRef, useState, useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { Recipe } from '../../lib/types'
import { RecipeCard } from './RecipeCard'

interface RecipeSectionRowProps {
  title: string
  recipes: Recipe[]
  /** When set, renders a "See all →" link that filters by this category */
  category?: string
}

export function RecipeSectionRow({ title, recipes, category }: RecipeSectionRowProps) {
  const [, setParams] = useSearchParams()
  const scrollRef = useRef<HTMLDivElement>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  function updateScrollButtons() {
    const el = scrollRef.current
    if (!el) return
    setCanScrollLeft(el.scrollLeft > 0)
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 1)
  }

  useEffect(() => {
    updateScrollButtons()
    const el = scrollRef.current
    if (!el) return
    el.addEventListener('scroll', updateScrollButtons, { passive: true })
    const observer = new ResizeObserver(updateScrollButtons)
    observer.observe(el)
    return () => {
      el.removeEventListener('scroll', updateScrollButtons)
      observer.disconnect()
    }
  }, [recipes])

  function scroll(direction: 'left' | 'right') {
    const el = scrollRef.current
    if (!el) return
    const cardWidth = el.firstElementChild?.getBoundingClientRect().width ?? 280
    const scrollAmount = cardWidth * 2 + 24 // 2 cards + gap
    el.scrollBy({ left: direction === 'right' ? scrollAmount : -scrollAmount, behavior: 'smooth' })
  }

  function handleSeeAll() {
    if (!category) return
    setParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('category', category)
      return next
    }, { replace: true })
  }

  if (recipes.length === 0) return null

  return (
    <section className="mb-10">
      {/* Header */}
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-xl font-bold text-content">{title}</h2>
        {category && (
          <button
            onClick={handleSeeAll}
            className="text-sm font-semibold text-brand transition-colors hover:text-brand-hover"
          >
            See all &rarr;
          </button>
        )}
      </div>

      {/* Scrollable row */}
      <div className="group/scroll relative">
        {/* Left arrow */}
        {canScrollLeft && (
          <button
            onClick={() => scroll('left')}
            className="absolute -left-3 top-1/2 z-10 hidden -translate-y-1/2 rounded-full border border-card-border bg-card/95 p-2 shadow-lg backdrop-blur transition-colors hover:border-brand-border hover:bg-control-hover md:block"
            aria-label="Scroll left"
          >
            <svg className="h-5 w-5 text-content-body" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        )}

        <div
          ref={scrollRef}
          className="scrollbar-hide flex gap-5 overflow-x-auto scroll-smooth pb-2"
        >
          {recipes.map((recipe) => (
            <div key={recipe.id} className="w-[260px] flex-shrink-0 sm:w-[280px]">
              <RecipeCard recipe={recipe} />
            </div>
          ))}
        </div>

        {/* Right arrow */}
        {canScrollRight && (
          <button
            onClick={() => scroll('right')}
            className="absolute -right-3 top-1/2 z-10 hidden -translate-y-1/2 rounded-full border border-card-border bg-card/95 p-2 shadow-lg backdrop-blur transition-colors hover:border-brand-border hover:bg-control-hover md:block"
            aria-label="Scroll right"
          >
            <svg className="h-5 w-5 text-content-body" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
            </svg>
          </button>
        )}
      </div>
    </section>
  )
}
