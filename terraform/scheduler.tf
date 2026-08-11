# ─── Instagram token auto-rotation ────────────────────────────────────────────
# A weekly Cloud Scheduler job calls the backend's internal refresh endpoint,
# which exchanges the current Instagram long-lived token for a fresh 60-day one
# and stores it as a new Secret Manager version. Weekly keeps the token far
# ahead of its 60-day expiry. Only created when an Instagram token is configured.
#
# The endpoint is authenticated at the app layer via the OIDC token minted here
# (the backend checks the token's email == the backend SA and the audience).
# Derived from var.mcp_resource_url (not the service's own .uri) to avoid a
# Terraform self-reference cycle in the Cloud Run env block.

locals {
  instagram_refresh_url = "${trimsuffix(var.mcp_resource_url, "/mcp")}/api/internal/instagram/refresh-token"
}

# Provision the Cloud Scheduler service agent explicitly — GCP only creates it
# lazily on first job creation, so the IAM grants below would fail without this.
# Unconditional: the weekly usage-report job below always exists (it only
# depends on the required var.alert_email), as does the budget-breaker reset job
# in billing.tf, so at least one scheduler job is always present.
resource "google_project_service_identity" "cloudscheduler" {
  provider = google-beta
  project  = var.gcp_project_id
  service  = "cloudscheduler.googleapis.com"
}

# Cloud Scheduler's service agent must be allowed to mint OIDC tokens as the
# backend SA so it can authenticate against internal endpoints (refresh-token,
# weekly usage report).
resource "google_service_account_iam_member" "scheduler_mints_backend_oidc" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_project_service_identity.cloudscheduler.email}"
  depends_on         = [google_project_service_identity.cloudscheduler]
}

resource "google_cloud_scheduler_job" "instagram_token_refresh" {
  count       = var.instagram_access_token != "" ? 1 : 0
  project     = var.gcp_project_id
  region      = var.gcp_region
  name        = "instagram-token-refresh"
  description = "Weekly refresh of the Instagram long-lived access token"
  schedule    = "0 4 * * 1" # 04:00 UTC every Monday
  time_zone   = "Etc/UTC"

  retry_config {
    retry_count = 3
  }

  http_target {
    http_method = "POST"
    uri         = local.instagram_refresh_url

    oidc_token {
      service_account_email = google_service_account.backend.email
      audience              = local.instagram_refresh_url
    }
  }

  depends_on = [google_project_service.required_apis]
}

# ─── Weekly usage report ──────────────────────────────────────────────────────
# A weekly Cloud Scheduler job calls the backend's internal usage-report
# endpoint, which aggregates the trailing 7 days of Cloud Run request logs
# (counts only — no IP addresses leave the endpoint) and emails a summary to
# var.alert_email. Unconditional: alert_email is a required variable, so this
# job always exists (unlike the Instagram job above, which is optional).

locals {
  usage_report_url = "${trimsuffix(var.mcp_resource_url, "/mcp")}/api/internal/usage/weekly-report"
}

resource "google_cloud_scheduler_job" "weekly_usage_report" {
  project     = var.gcp_project_id
  region      = var.gcp_region
  name        = "weekly-usage-report"
  description = "Weekly email summary of backend request traffic"
  schedule    = "0 13 * * 1" # 13:00 UTC every Monday
  time_zone   = "Etc/UTC"

  retry_config {
    retry_count = 3
  }

  http_target {
    http_method = "POST"
    uri         = local.usage_report_url

    oidc_token {
      service_account_email = google_service_account.backend.email
      audience              = local.usage_report_url
    }
  }

  depends_on = [google_project_service.required_apis]
}

# ─── Budget breaker reset ─────────────────────────────────────────────────────
# Closes the circuit breaker at month rollover. The billing budget window resets
# on the 1st, but the Cloud Run max_instance_count = 0 the killer set does not —
# without this the site stays down until someone notices.
#
# The function is idempotent (no-op when already at 1 instance), so this is a
# cheap no-op in every month the breaker never tripped.

resource "google_cloud_scheduler_job" "budget_breaker_reset" {
  project     = var.gcp_project_id
  region      = var.gcp_region
  name        = "budget-breaker-reset"
  description = "Restore mfs-backend scaling after a budget breaker trip"
  schedule    = "0 8 1 * *" # 08:00 UTC on the 1st, after the budget window rolls over
  time_zone   = "Etc/UTC"

  retry_config {
    retry_count = 3
  }

  http_target {
    http_method = "POST"
    uri         = google_cloudfunctions2_function.budget_resetter.service_config[0].uri

    oidc_token {
      service_account_email = google_service_account.budget_killer.email
      audience              = google_cloudfunctions2_function.budget_resetter.service_config[0].uri
    }
  }

  depends_on = [
    google_project_service.required_apis,
    google_cloud_run_v2_service_iam_member.budget_resetter_invoker,
    google_service_account_iam_member.scheduler_mints_budget_killer_oidc,
  ]
}
