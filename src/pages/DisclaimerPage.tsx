import { Link } from 'react-router-dom'
import { usePageMeta } from '../hooks/usePageMeta'

// Hardcoded for the same reason as PrivacyPage: this is a standing statement,
// not editorial copy, and it should never fall back to a stale default.
const LAST_UPDATED = 'September 18, 2026'

const H2 = 'font-display text-2xl font-bold text-content pt-4'

export function DisclaimerPage() {
  usePageMeta({
    title: 'Disclaimer',
    description:
      'How to use the recipes, nutrition figures and Sous Chef assistant on MadeForSeconds safely.',
  })

  return (
    <article className="mx-auto max-w-3xl px-4 py-12 md:py-20">
      <header className="space-y-3">
        <h1 className="font-display text-4xl font-bold text-content md:text-5xl">Disclaimer</h1>
        <p className="text-sm text-content-muted">Last updated: {LAST_UPDATED}</p>
      </header>

      <div className="mt-8 space-y-6 text-lg leading-relaxed text-content-body">
        <p>
          MadeForSeconds is one person sharing recipes he cooks. Everything here is offered in
          good faith and without any guarantee. You are the one in your kitchen — please use
          your own judgement.
        </p>

        <h2 className={H2}>Recipes</h2>
        <p>
          Recipes are shared as-is. They are written from how I cook them, not tested in a
          commercial test kitchen, and results will vary with your ingredients, your equipment,
          and your oven.
        </p>
        <p>
          Cooking times and temperatures in a recipe are a guide. <strong>Cook food to a safe
          internal temperature and check it with a thermometer</strong> rather than relying on
          time, colour, or clear juices. If a step here disagrees with current food-safety
          guidance from a body like the USDA, follow the guidance, not me.
        </p>

        <h2 className={H2}>Allergies and dietary needs</h2>
        <p>
          Recipes on this site do not carry allergen labelling, and ingredient lists will not
          catch what a manufacturer changed. If you cook for someone with an allergy,
          intolerance, or medical dietary requirement, <strong>read the labels on the products
          you actually buy</strong> and account for cross-contamination yourself. I cannot
          verify either.
        </p>

        <h2 className={H2}>Nutrition figures</h2>
        <p>
          Where a recipe shows nutrition information, those numbers are <strong>estimates I
          entered by hand</strong>. Nothing on this site measures or calculates them. They
          change with brands, substitutions, and how much of something you actually use, and
          they scale arithmetically when you change the serving count.
        </p>
        <p>
          Treat them as a rough guide, not a measurement, and never as a substitute for advice
          from a doctor or a registered dietitian.
        </p>

        <h2 className={H2}>The Sous Chef assistant</h2>
        <p>
          Sous Chef is an AI. It can be confidently wrong, and it is not a professional chef,
          a doctor, or a dietitian. Check anything that matters — especially temperatures,
          timings, and substitutions — before you rely on it.
        </p>
        <p>
          It is built to refuse rather than guess on the things where bad advice is dangerous:
          home and pressure canning, curing and nitrites, fermentation safety, sous-vide
          pasteurisation, wild-foraged ingredients, and food for infants under 12 months. If you
          ask about those, it will point you to an authoritative source instead. Please use it.
        </p>

        <h2 className={H2}>No liability</h2>
        <p>
          This site and everything on it are provided without warranty of any kind. I am not
          liable for any loss, injury, illness, or damage arising from using the recipes, the
          nutrition figures, or the assistant. Cooking carries risk — heat, knives, raw
          ingredients, and allergens — and that risk is yours to manage.
        </p>

        <div className="rounded-xl border border-card-border bg-card-muted p-4 text-xs text-content-muted space-y-1.5">
          <p>
            MadeForSeconds is an independent personal project, not a company, and this page is
            not legal or medical advice.
          </p>
          <p>
            See also the{' '}
            <Link to="/privacy/" className="underline hover:text-content-body">
              privacy policy
            </Link>
            , and the{' '}
            <Link to="/support/" className="underline hover:text-content-body">
              support page
            </Link>{' '}
            for how donations work.
          </p>
        </div>
      </div>
    </article>
  )
}
