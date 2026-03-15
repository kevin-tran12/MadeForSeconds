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

resource "google_secret_manager_secret_version" "admin_emails_initial" {
  secret      = google_secret_manager_secret.admin_emails.id
  secret_data = var.admin_emails
}

# MCP API key — bearer token for Claude Projects to create recipes via MCP
resource "google_secret_manager_secret" "mcp_api_key" {
  project   = var.gcp_project_id
  secret_id = "mcp-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "mcp_api_key_initial" {
  secret      = google_secret_manager_secret.mcp_api_key.id
  secret_data = var.mcp_api_key
}

# Redis URL — contains embedded credentials; only created when redis_url is provided
resource "google_secret_manager_secret" "redis_url" {
  count     = var.redis_url != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "redis-url"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "redis_url_initial" {
  count       = var.redis_url != "" ? 1 : 0
  secret      = google_secret_manager_secret.redis_url[0].id
  secret_data = var.redis_url
}
