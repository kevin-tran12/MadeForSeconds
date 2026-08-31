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

# Cloud Scheduler's service agent must be allowed to mint OIDC tokens as the
# backend SA so it can authenticate against internal endpoints (refresh-token,
# weekly usage report).
resource "google_service_account_iam_member" "scheduler_mints_backend_oidc" {
  service_account_id = var.backend_sa_name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${var.scheduler_agent_email}"

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
      service_account_email = var.backend_sa_email
      audience              = local.instagram_refresh_url
    }
  }
}

# ─── Weekly usage report ──────────────────────────────────────────────────────
# A weekly Cloud Scheduler job calls the backend's internal usage-report
# endpoint, which aggregates the trailing 7 days of Cloud Run request logs
# (counts only — no IP addresses leave the endpoint) and emails a summary to
# var.alert_email. Runs in production only (var.deployment_target) — Cloud
# Scheduler's 3-job free limit is per billing account, already fully spent by
# production's own three jobs, so staging keeps its headroom free. Was
# unconditional before staging existed; alert_email being a required variable
# no longer implies this job always exists, only that it exists when it can.

locals {
  usage_report_url = "${trimsuffix(var.mcp_resource_url, "/mcp")}/api/internal/usage/weekly-report"
}

resource "google_cloud_scheduler_job" "weekly_usage_report" {
  count = var.deployment_target == "production" ? 1 : 0

  project     = var.gcp_project_id
  region      = var.gcp_region
  name        = "weekly-usage-report"
  description = "Weekly email summary of backend request traffic"
  schedule    = "0 13 * * 1" # 13:00 UTC every Monday
  time_zone   = "Etc/UTC"

  retry_config {
    retry_count          = 3
    min_backoff_duration = "60s"
  }

  http_target {
    http_method = "POST"
    uri         = local.usage_report_url

    oidc_token {
      service_account_email = var.backend_sa_email
      audience              = local.usage_report_url
    }
  }
}

