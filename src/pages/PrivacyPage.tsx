import { Link } from 'react-router-dom'
import { usePageMeta } from '../hooks/usePageMeta'

// Deliberately hardcoded rather than CMS-driven: a policy needs a reliable
// "last updated" date and must never silently fall back to stale defaults.
// Update this whenever the copy below changes.
const LAST_UPDATED = 'September 18, 2026'
const CONTACT_EMAIL = 'madeforseconds@gmail.com'

const H2 = 'font-display text-2xl font-bold text-content pt-4'

export function PrivacyPage() {
  usePageMeta({
    title: 'Privacy Policy',
    description:
      'What MadeForSeconds collects, who processes it, how long it is kept, and how to see or delete your data.',
  })

  return (
    <article className="mx-auto max-w-3xl px-4 py-12 md:py-20">
      <header className="space-y-3">
        <h1 className="font-display text-4xl font-bold text-content md:text-5xl">
          Privacy Policy
        </h1>
        <p className="text-sm text-content-muted">Last updated: {LAST_UPDATED}</p>
      </header>

      <div className="mt-8 space-y-6 text-lg leading-relaxed text-content-body">
        <p>
          MadeForSeconds is a personal recipe site. This page describes exactly what it
          collects, who else sees it, and what you can do about it. It describes what the
          site actually does — not what a template says a site might do.
        </p>

        <div className="rounded-2xl bg-card-muted p-6 md:p-8 border border-card-border">
          <h2 className="font-display text-2xl font-bold text-content">The short version</h2>
          <ul className="mt-4 space-y-2 text-base">
            <li>There is no advertising, analytics, or tracking of any kind.</li>
            <li>The site sets no cookies.</li>
            <li>You can read every recipe without signing in or giving me anything.</li>
            <li>Card details never touch this site — payments are handled by Stripe.</li>
            <li>You can download or delete your data at any time.</li>
          </ul>
        </div>

        <h2 className={H2}>No tracking, no advertising</h2>
        <p>
          There are no analytics tools, no advertising networks, no marketing pixels, and no
          third-party tracking scripts on this site. I do not build profiles of visitors, and I
          do not sell or share personal information for advertising. The site's Content Security
          Policy blocks third-party scripts outright, so a tracker could not run here even by
          accident.
        </p>
        <p>
          The only usage measurement is a weekly summary I send myself, built from aggregate
          server request counts. It contains totals and popular page paths — no visitor
          identities.
        </p>

        <h2 className={H2}>Cookies and browser storage</h2>
        <p>
          This site sets no cookies, which is why you will not find a cookie banner. It does use
          your browser's local storage for preferences that stay on your own device and are
          never sent to me:
        </p>
        <ul className="ml-6 list-disc space-y-1.5 text-base">
          <li>Your light or dark theme choice.</li>
          <li>Whether you prefer metric or imperial units.</li>
          <li>Which ingredients you have ticked off on a recipe.</li>
        </ul>
        <p>
          If you sign in, Google's authentication library also stores your session in the
          browser so you stay signed in. Clearing your browser data removes all of this.
        </p>

        <h2 className={H2}>If you browse without signing in</h2>
        <p>
          You can read everything without an account. My server keeps ordinary web request logs,
          and your IP address is held briefly to enforce rate limits — a defence against abuse,
          not a way of identifying you.
        </p>

        <h2 className={H2}>If you sign in</h2>
        <p>
          Signing in uses Google. I never see or handle your Google password. What I store about
          a signed-in reader is deliberately minimal: an account identifier, when you first
          visited, when you were last seen, how many assistant questions you have asked, and —
          only if you choose to fill it in — your self-described cooking experience.
        </p>
        <p>
          That record holds <strong>no email address and no name</strong>. Your display name is
          read from your Google profile by your own browser and is never sent to my server.
        </p>

        <h2 className={H2}>If you donate</h2>
        <p>
          Payments go through Stripe's own hosted checkout. Card numbers, billing addresses, and
          payment credentials go directly to Stripe and never reach this site.
        </p>
        <p>
          What I store is your email address, the amount, the date, and Stripe's reference ids,
          so I can recognise supporters and handle cancellations. A separate payment ledger
          records amounts against a one-way hash of your email rather than the address itself.
        </p>
        <p>
          Supporters are listed publicly only if they choose to be. Nothing appears on the
          supporters wall unless you type a display name into the optional form after checkout.
          Notes are shown only if you tick the box to make yours public <em>and</em> I approve
          it. Your email address, donation amount, and payment references are never public.
        </p>

        <h2 className={H2}>If you use the Sous Chef assistant</h2>
        <p>
          Questions you ask the cooking assistant are sent to Anthropic's Claude API to generate
          an answer, along with the recipe you are viewing and your cooking-experience notes if
          you set them. Your email, name, and account id are <strong>not</strong> sent.
        </p>
        <p>
          Before anything reaches the model, an automatic check blocks messages containing
          personal details — email addresses, phone numbers, card numbers, postal addresses,
          ID numbers, and dates of birth. If it trips, your message is refused and is not sent,
          logged, or stored.
        </p>
        <p>
          Your questions are not kept. The one exception is if you submit feedback on an answer,
          which stores that question, the answer, and your comment for 180 days before being
          deleted automatically.
        </p>

        <h2 className={H2}>Who else processes your data</h2>
        <ul className="ml-6 list-disc space-y-1.5 text-base">
          <li><strong>Google</strong> — sign-in, and the cloud services that host the database, files, and server logs.</li>
          <li><strong>Stripe</strong> — payment processing for donations.</li>
          <li><strong>Anthropic</strong> — generating Sous Chef answers.</li>
          <li><strong>Resend</strong> — sending the few transactional emails described below.</li>
          <li><strong>Cloudflare</strong> — serving the site itself.</li>
          <li><strong>Upstash</strong> — short-lived caching and rate-limit counters.</li>
          <li><strong>Google Fonts</strong> — the site's typefaces load from Google's servers, which means Google receives your IP address and browser details on each page view.</li>
        </ul>

        <h2 className={H2}>Email</h2>
        <p>
          I do not run a newsletter and will not add you to a mailing list. The only emails this
          site sends to a visitor are ones you ask for: a link to confirm cancelling a recurring
          donation, or a link to connect a past donation to your account.
        </p>

        <h2 className={H2}>How long things are kept</h2>
        <ul className="ml-6 list-disc space-y-1.5 text-base">
          <li>Assistant feedback — 180 days, then deleted automatically.</li>
          <li>Rate-limiting records, which include your IP address — minutes to an hour.</li>
          <li>Your reader profile — until you delete it, which you can do yourself at any time.</li>
          <li>
            Donation records — kept as financial records. I can delete the account link and
            anything the assistant stored, but not the record of the payment itself.
          </li>
        </ul>

        <h2 className={H2}>Your rights</h2>
        <p>
          Wherever you live, you can ask for a copy of your data, correct it, or have it
          deleted. If you are in the UK, EU, or European Economic Area, you also have the right
          to object to or restrict processing, to data portability, and to complain to your
          local data protection authority. If you are in California, you have the right to know
          what is collected, to request deletion, and not to be discriminated against for
          exercising those rights — and there is nothing to opt out of, because I do not sell or
          share personal information.
        </p>
        <p>
          Two of these are self-service while signed in: you can download everything stored
          about you as a file, and you can delete your reader profile and assistant feedback.
          For anything else — including correcting a donation record — email me and I will
          respond within 30 days.
        </p>
        <p>
          Where a legal basis is required: running your account and answering your questions is
          necessary to provide a service you asked for; handling donations is necessary for the
          payment you initiated and to meet financial record-keeping obligations; keeping the
          site secure and abuse-free is a legitimate interest.
        </p>
        <p>
          Deleting your reader profile does not erase donation records, which are financial
          records I am required to retain. They contain nothing you did not already give Stripe.
        </p>

        <h2 className={H2}>Changes</h2>
        <p>
          If this policy changes, the date at the top changes with it. There is no archive of
          previous versions.
        </p>

        <h2 className={H2}>Contact</h2>
        <p>
          Questions about your data, or a request to see, correct, or delete it:{' '}
          <a href={`mailto:${CONTACT_EMAIL}`} className="underline hover:text-content">
            {CONTACT_EMAIL}
          </a>
          .
        </p>

        <div className="rounded-xl border border-card-border bg-card-muted p-4 text-xs text-content-muted space-y-1.5">
          <p>
            MadeForSeconds is an independent personal project, not a company. This page explains
            how the site handles data; it is not legal advice.
          </p>
          <p>
            For how donations work, see the{' '}
            <Link to="/support/" className="underline hover:text-content-body">
              support page
            </Link>
            .
          </p>
        </div>
      </div>
    </article>
  )
}
