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

# Anthropic API key — used by the recipe parser endpoint
resource "google_secret_manager_secret" "anthropic_api_key" {
  project   = var.gcp_project_id
  secret_id = "anthropic-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "anthropic_api_key_initial" {
  secret      = google_secret_manager_secret.anthropic_api_key.id
  secret_data = var.anthropic_api_key

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

# Stripe secret key — only created when stripe_secret_key is provided
resource "google_secret_manager_secret" "stripe_secret_key" {
  count     = var.stripe_secret_key != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "stripe-secret-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "stripe_secret_key_initial" {
  count       = var.stripe_secret_key != "" ? 1 : 0
  secret      = google_secret_manager_secret.stripe_secret_key[0].id
  secret_data = var.stripe_secret_key

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Stripe webhook signing secret
resource "google_secret_manager_secret" "stripe_webhook_secret" {
  count     = var.stripe_webhook_secret != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "stripe-webhook-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "stripe_webhook_secret_initial" {
  count       = var.stripe_webhook_secret != "" ? 1 : 0
  secret      = google_secret_manager_secret.stripe_webhook_secret[0].id
  secret_data = var.stripe_webhook_secret

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Subscriber JWT signing secret
resource "google_secret_manager_secret" "subscriber_jwt_secret" {
  count     = var.subscriber_jwt_secret != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "subscriber-jwt-secret"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "subscriber_jwt_secret_initial" {
  count       = var.subscriber_jwt_secret != "" ? 1 : 0
  secret      = google_secret_manager_secret.subscriber_jwt_secret[0].id
  secret_data = var.subscriber_jwt_secret

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Resend API key — for sending cancellation confirmation emails
resource "google_secret_manager_secret" "resend_api_key" {
  count     = var.resend_api_key != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "resend-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_version" "resend_api_key_initial" {
  count       = var.resend_api_key != "" ? 1 : 0
  secret      = google_secret_manager_secret.resend_api_key[0].id
  secret_data = var.resend_api_key

  lifecycle {
    ignore_changes = [secret_data]
  }
}
