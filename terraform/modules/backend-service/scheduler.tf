# ─── Social token auto-rotation ───────────────────────────────────────────────
# One Cloud Scheduler job for every social platform's token. It calls the
# backend's shared refresh endpoint, which rotates each configured platform
# independently (Instagram today: exchange the long-lived token for a fresh
# 60-day one and write it as a new Secret Manager version) and records the
# outcome on Firestore config/social for the MCP social_status tool.
#
# Twice a month, not weekly, on purpose: every refresh writes a Secret Manager
# version, and versions are billed per active version-month above the free
# allowance, so cadence is a cost lever. Meta only requires a token to be at
# least 24 hours old and still valid to refresh it, and each refresh renews
# the full 60 days, so the 1st and the 15th leaves 45+ days of margin.
#
# What went wrong before (Cloud Logging, Aug 2026): the weekly job 500'd on
# every attempt because the token it was given had already expired — Meta's
# "Session has expired on Sunday, 16-Aug-26" — i.e. it was seeded near the end
# of its life and the first run came a few hours too late. Nothing alerted,
# so it failed silently for weeks. Two changes follow from that: the alert
# policies in social_alerts.tf, and the operator step in docs/DEPLOYMENT.md
# to run this job by hand immediately after seeding a token so it is
# exchanged for a fresh one right away.
#
# The endpoint is authenticated at the app layer via the OIDC token minted here
# (the backend checks the token's email == the backend SA and the audience).
# Derived from var.mcp_resource_url (not the service's own .uri) to avoid a
# Terraform self-reference cycle in the Cloud Run env block.

locals {
  # Legacy single-platform endpoint, still served; its audience env var stays.
  instagram_refresh_url = "${trimsuffix(var.mcp_resource_url, "/mcp")}/api/internal/instagram/refresh-token"
  social_refresh_url    = "${trimsuffix(var.mcp_resource_url, "/mcp")}/api/internal/social/refresh-tokens"
}

# Cloud Scheduler's service agent must be allowed to mint OIDC tokens as the
# backend SA so it can authenticate against internal endpoints (refresh-token,
# weekly usage report).
resource "google_service_account_iam_member" "scheduler_mints_backend_oidc" {
  service_account_id = var.backend_sa_name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${var.scheduler_agent_email}"

}

moved {
  from = google_cloud_scheduler_job.instagram_token_refresh
  to   = google_cloud_scheduler_job.social_token_refresh
}

resource "google_cloud_scheduler_job" "social_token_refresh" {
  count       = var.instagram_access_token != "" ? 1 : 0
  project     = var.gcp_project_id
  region      = var.gcp_region
  name        = "social-token-refresh"
  description = "Twice-monthly refresh of every configured social platform token (Instagram)"
  schedule    = "0 4 1,15 * *" # 04:00 UTC on the 1st and the 15th
  time_zone   = "Etc/UTC"

  retry_config {
    retry_count          = 3
    min_backoff_duration = "60s"
  }

  http_target {
    http_method = "POST"
    uri         = local.social_refresh_url

    oidc_token {
      service_account_email = var.backend_sa_email
      audience              = local.social_refresh_url
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

