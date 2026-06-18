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
# lazily on first job creation, so the IAM grant below would fail without this.
resource "google_project_service_identity" "cloudscheduler" {
  provider = google-beta
  count    = var.instagram_access_token != "" ? 1 : 0
  project  = var.gcp_project_id
  service  = "cloudscheduler.googleapis.com"
}

# Cloud Scheduler's service agent must be allowed to mint OIDC tokens as the
# backend SA so it can authenticate against the refresh endpoint.
resource "google_service_account_iam_member" "scheduler_mints_backend_oidc" {
  count              = var.instagram_access_token != "" ? 1 : 0
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_project_service_identity.cloudscheduler[0].email}"
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
