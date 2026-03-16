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

    # Google OAuth — users authenticate via their Google Account.
    # No password stored in Identity Platform; 2FA inherited from Google Account.
    # The backend admin check is still email-based (admin_emails allowlist), unchanged.
    #
    # Frontend: swap signInWithEmailAndPassword for signInWithPopup(new GoogleAuthProvider())
    google {
      enabled = true
    }
  }

  depends_on = [google_project_service.required_apis]
}
