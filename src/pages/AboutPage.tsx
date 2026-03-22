import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { subscriberApi } from '../lib/api'
import { usePageContent } from '../hooks/usePageContent'

const ABOUT_DEFAULTS = {
  heading: 'About MadeForSeconds',
  body: [
    'MadeForSeconds is where I keep and share the recipes I cook.',
    "It started as a place to organize my own recipes so they didn't get lost in random notes, screenshots, and half-written documents. Eventually it turned into this site.",
    'My background is a bit all over the place. I spent most of my early working years in the food and service industry starting at 16, mostly serving and bartending, with some time around kitchens as well. Restaurants teach you a lot about food, but they also teach speed, repetition, and how to handle chaos while people are hungry.',
    "In my mid-20s I moved into software engineering and spent the next four years building applications. More recently I've been moving deeper into cloud infrastructure.",
    "This project sits somewhere in the overlap of those worlds. It's a place for recipes I want to keep cooking and also a small technical playground where I can build something real.",
    "The food here doesn't stick to one cuisine or style. Some recipes are quick things to make on a random night. Others take time. If it tastes good and I want to make it again, it gets written down here.",
    'No long life stories before the recipe. Just ingredients, steps, and food that works.',
  ].join('\n\n'),
  callout_title: 'Why "MadeForSeconds"?',
  callout_body: 'Because the best compliment a dish can get is someone going back for another plate.',
  follow_heading: 'Follow the Journey',
  thank_you_message: 'Thank you to everyone who has supported this site. You help keep it going.',
}

export function AboutPage() {
  const [supporters, setSupporters] = useState<{ display_name: string; note?: string }[]>([])
  const page = usePageContent('about', ABOUT_DEFAULTS)

  useEffect(() => {
    subscriberApi.listSupporters().then((list) => setSupporters(list.slice(0, 50))).catch(() => {})
  }, [])

  return (
    <article className="mx-auto max-w-4xl px-4 py-12 md:py-20">
      <div className="flex flex-col gap-12 md:flex-row md:items-start md:gap-16">

        {/* Left column: socials + supporters */}
        <div className="shrink-0 space-y-10 md:w-1/3">

          {/* Follow */}
          <div className="space-y-4">
            <h2 className="font-display text-xl font-bold text-gray-900">{page.follow_heading}</h2>
            <div className="flex flex-col gap-3">
              <a
                href="https://instagram.com/madeforseconds"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white p-3 text-sm font-medium text-gray-700 transition-all hover:border-primary-200 hover:bg-primary-50 hover:text-primary-700 shadow-sm"
              >
                Instagram
              </a>
              <a
                href="https://tiktok.com/@madeforseconds"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white p-3 text-sm font-medium text-gray-700 transition-all hover:border-primary-200 hover:bg-primary-50 hover:text-primary-700 shadow-sm"
              >
                TikTok
              </a>
              <a
                href="https://linktr.ee/madeforseconds"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-3 rounded-xl border border-gray-200 bg-white p-3 text-sm font-medium text-gray-700 transition-all hover:border-primary-200 hover:bg-primary-50 hover:text-primary-700 shadow-sm"
              >
                Linktree
              </a>
            </div>
          </div>

          {/* Supporters */}
          <div id="supporters" className="space-y-4">
            <h2 className="font-display text-xl font-bold text-gray-900">Supporters</h2>
            {supporters.length > 0 ? (
              <>
                <p className="text-sm text-gray-500">
                  {page.thank_you_message}
                </p>
                <div className="space-y-3">
                  {supporters.map((s, i) => (
                    <div key={i}>
                      <p className="text-sm font-semibold text-gray-800">{s.display_name}</p>
                      {s.note && (
                        <p className="text-xs italic text-gray-500 mt-0.5">&ldquo;{s.note}&rdquo;</p>
                      )}
                    </div>
                  ))}
                </div>
                <Link
                  to="/support"
                  className="inline-flex rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-600 transition-colors"
                >
                  Join them
                </Link>
              </>
            ) : (
              <>
                <p className="text-sm text-gray-500">
                  Be the first to support MadeForSeconds.
                </p>
                <Link
                  to="/support"
                  className="inline-flex rounded-lg bg-amber-500 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-600 transition-colors"
                >
                  Support us
                </Link>
              </>
            )}
          </div>

        </div>

        {/* Right column: main content */}
        <div className="flex-1 space-y-8">
          <header>
            <h1 className="font-display text-4xl font-bold text-gray-900 md:text-5xl lg:text-6xl">
              {page.heading}
            </h1>
          </header>

          <div className="space-y-6 text-lg leading-relaxed text-gray-700">
            {page.body.split('\n\n').map((para, i) => (
              <p key={i}>{para}</p>
            ))}

            <div className="rounded-2xl bg-gray-50 p-6 md:p-8 border border-gray-100">
              <h2 className="font-display text-2xl font-bold text-gray-900">{page.callout_title}</h2>
              <p className="mt-4">
                {page.callout_body}
              </p>
            </div>

            <div className="pt-4">
              <h2 className="font-display text-2xl font-bold text-gray-900">The Stack</h2>
              <p className="mt-4 text-base text-gray-600">
                This site also doubles as a place where I experiment with cloud infrastructure.
              </p>
              <ul className="mt-4 grid grid-cols-2 gap-4 text-sm font-medium text-gray-500">
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-primary-400"></span>
                  React + TypeScript
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-primary-400"></span>
                  FastAPI (Python)
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-primary-400"></span>
                  Google Cloud Run
                </li>
                <li className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-primary-400"></span>
                  Firebase Firestore
                </li>
              </ul>
            </div>
          </div>
        </div>

      </div>
    </article>
  )
}
