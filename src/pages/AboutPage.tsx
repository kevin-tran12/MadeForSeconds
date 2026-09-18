import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { subscriberApi } from '../lib/api'
import { usePageContent } from '../hooks/usePageContent'

const ABOUT_DEFAULTS = {
  heading: 'About MadeForSeconds',
  body: [
    'MadeForSeconds is where I keep and share the recipes I actually cook.',
    'It started because my recipes were scattered everywhere: notes, screenshots, text messages, bookmarks, and half-written documents. I wanted one place to keep the ones worth making again, so I built it.',
    'Food has been part of my life a lot longer than software. I started working in restaurants at 16 and spent most of my early working years in the service industry, mostly serving and bartending, with some time around kitchens too. Restaurants teach you a lot beyond food. You learn how to move quickly, communicate clearly, improvise when something goes wrong, and keep things moving when everyone needs something at once.',
    'In my mid-20s, I moved into software engineering. I spent the next several years building production applications, and eventually started MadeForSeconds as a way to combine both sides of my background.',
    'Today, the site is part recipe collection and part product I get to continuously improve. I build the application, the publishing tools, the automation, and the infrastructure behind it. If something feels repetitive or annoying to manage, I usually end up finding a way to make it simpler.',
    "The food itself doesn't follow one cuisine or style. Some recipes are quick weeknight meals. Others take an unreasonable amount of time because sometimes that's the fun part.",
    "The only real requirement is that I'd make it again.",
    'And there are no three-page life stories before the recipe. Just the food.',
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
            <h2 className="font-display text-xl font-bold text-content">{page.follow_heading}</h2>
            <div className="flex flex-col gap-3">
              <a
                href="https://instagram.com/madeforseconds"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-3 rounded-xl border border-card-border bg-card p-3 text-sm font-medium text-content-body transition-all hover:border-brand-border hover:bg-brand-surface hover:text-brand shadow-sm"
              >
                Instagram
              </a>
              <a
                href="https://tiktok.com/@madeforseconds"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-3 rounded-xl border border-card-border bg-card p-3 text-sm font-medium text-content-body transition-all hover:border-brand-border hover:bg-brand-surface hover:text-brand shadow-sm"
              >
                TikTok
              </a>
              <a
                href="https://linktr.ee/madeforseconds"
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-3 rounded-xl border border-card-border bg-card p-3 text-sm font-medium text-content-body transition-all hover:border-brand-border hover:bg-brand-surface hover:text-brand shadow-sm"
              >
                Linktree
              </a>
            </div>
          </div>

          {/* Supporters */}
          <div id="supporters" className="space-y-4">
            <h2 className="font-display text-xl font-bold text-content">Supporters</h2>
            {supporters.length > 0 ? (
              <>
                <p className="text-sm text-content-muted">
                  {page.thank_you_message}
                </p>
                <div className="space-y-3">
                  {supporters.map((s, i) => (
                    <div key={i}>
                      <p className="text-sm font-semibold text-content">{s.display_name}</p>
                      {s.note && (
                        <p className="text-xs italic text-content-muted mt-0.5">&ldquo;{s.note}&rdquo;</p>
                      )}
                    </div>
                  ))}
                </div>
                <Link
                  to="/support/"
                  className="inline-flex rounded-lg bg-cta px-4 py-2 text-sm font-semibold text-cta-content hover:bg-cta-hover transition-colors"
                >
                  Join them
                </Link>
              </>
            ) : (
              <>
                <p className="text-sm text-content-muted">
                  Be the first to support MadeForSeconds.
                </p>
                <Link
                  to="/support/"
                  className="inline-flex rounded-lg bg-cta px-4 py-2 text-sm font-semibold text-cta-content hover:bg-cta-hover transition-colors"
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
            <h1 className="font-display text-4xl font-bold text-content md:text-5xl lg:text-6xl">
              {page.heading}
            </h1>
          </header>

          <div className="space-y-6 text-lg leading-relaxed text-content-body">
            {page.body.split('\n\n').map((para, i) => (
              <p key={i}>{para}</p>
            ))}

            <div className="rounded-2xl bg-card-muted p-6 md:p-8 border border-card-border">
              <h2 className="font-display text-2xl font-bold text-content">{page.callout_title}</h2>
              <p className="mt-4">
                {page.callout_body}
              </p>
            </div>
          </div>
        </div>

      </div>
    </article>
  )
}
