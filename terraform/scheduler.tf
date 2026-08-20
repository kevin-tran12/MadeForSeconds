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
