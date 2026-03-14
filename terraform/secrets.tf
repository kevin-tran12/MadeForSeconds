# ─── Secret Manager ───────────────────────────────────────────────────────────
# Stores sensitive config values outside of Terraform state and plaintext env vars.
# The secret CONTAINER is created here. The secret VALUE must be set manually:
#
#   echo -n "your@email.com" | gcloud secrets versions add admin-emails --data-file=-
#
# To update the value later, add a new version the same way. Cloud Run picks it
# up on the next deployment or manual revision update.

resource "google_secret_manager_secret" "admin_emails" {
  project   = var.gcp_project_id
  secret_id = "admin-emails"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required_apis]
}
