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
  authorized_domains = [
    "localhost",
    "made-for-seconds.firebaseapp.com",
    "made-for-seconds.web.app",
    "madeforseconds.com",
    "madeforseconds.pages.dev",
    "39e71d85.madeforseconds.pages.dev",
  ]

  depends_on = [google_project_service.required_apis]
}
