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

  depends_on = [google_project_service.required_apis]
}
