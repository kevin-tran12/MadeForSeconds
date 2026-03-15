# ─── Secret Manager ───────────────────────────────────────────────────────────
# Terraform creates the secret container and seeds an initial value from tfvars.
# After the first apply, lifecycle { ignore_changes = [secret_data] } ensures
# subsequent applies never touch the value — rotate secrets out-of-band:
#
#   echo -n "new-value" | gcloud secrets versions add <secret-id> --data-file=-
#
# Cloud Run always reads "latest", so it picks up new versions automatically
# on the next deployment or manual revision update.

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

  lifecycle {
    ignore_changes = [secret_data]
  }
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

  lifecycle {
    ignore_changes = [secret_data]
  }
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

  lifecycle {
    ignore_changes = [secret_data]
  }
}
