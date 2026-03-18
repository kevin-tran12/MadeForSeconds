# ─── Identity Platform ────────────────────────────────────────────────────────
# Always-free tier: 49,999 monthly active users (Tier 1: email/password)

resource "google_identity_platform_config" "default" {
  project = var.gcp_project_id

  sign_in {
    allow_duplicate_emails = false

    email {
      enabled           = true
      password_required = true
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
