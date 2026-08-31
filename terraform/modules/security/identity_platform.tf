# ─── Identity Platform ────────────────────────────────────────────────────────
# Always-free tier: 49,999 monthly active users (Tier 1: email/password)

resource "google_identity_platform_config" "default" {
  project = var.gcp_project_id

  sign_in {
    allow_duplicate_emails = false

    # Email/password sign-in is disabled: the admin UI authenticates solely via
    # GoogleAuthProvider (see src/lib/auth.ts), so the password path was enabled
    # but unreachable. Leaving it on kept a live SCRYPT signer key in the project
    # config for a flow nobody used. Existing user records are unaffected — this
    # disables the sign-in *method*, and Google still resolves the same accounts
    # by email because allow_duplicate_emails is false.
    #
    # Google sign-in itself is configured in the Identity Platform console, not
    # here, so this change cannot disable it.
    email {
      enabled           = false
      password_required = false
    }
  }

  # Domains allowed to initiate Firebase auth flows.
  # Must include every hostname where the login UI is served.
  #
  # Cloudflare Pages gives every branch a preview at <branch>.madeforseconds.pages.dev,
  # and this list does NOT cover those — wildcards are not supported here, so each
  # would need adding by hand. That is why a one-off deploy hash
  # (39e71d85.madeforseconds.pages.dev) accumulated here and was removed. Admin
  # sign-in is only exercised on the production hostname; if you ever need it on a
  # preview, add that host temporarily and take it out again afterwards.
  #
  # Split by deployment_target (Epic 8) — this resource is created in BOTH
  # environments via the shared module, and until this was caught (while
  # actually setting up staging's own frontend, PR 9), it used production's
  # exact domain list unconditionally. Staging's own firebaseapp.com/web.app
  # host are project-derived, not copy-pasted; its Cloudflare Pages hostname
  # gets added here once that project exists and the real hostname is known.
  authorized_domains = var.deployment_target == "production" ? [
    "localhost",
    # Load-bearing: this is VITE_FIREBASE_AUTH_DOMAIN, the origin that handles the
    # OAuth redirect. Removing it breaks signInWithPopup, however unused it looks.
    "made-for-seconds.firebaseapp.com",
    # Firebase Hosting default. Nothing is served from it — the site is on Pages —
    # but it costs nothing to keep and is awkward to prove unused.
    "made-for-seconds.web.app",
    "madeforseconds.com",
    "madeforseconds.pages.dev",
    ] : [
    "localhost",
    "${var.gcp_project_id}.firebaseapp.com",
    "${var.gcp_project_id}.web.app",
    # Cloudflare Pages branch alias — a dedicated long-lived `staging` git
    # branch (not a short-lived PR branch), so this stays stable rather than
    # needing an update on every feature branch. Verified live: resolves and
    # serves the real frontend (2026-08-30).
    "staging.madeforseconds.pages.dev",
  ]
}
