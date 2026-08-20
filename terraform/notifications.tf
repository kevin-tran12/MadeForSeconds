# ─── Shared notification channel ──────────────────────────────────────────────
# One email address for every alert: budget thresholds, the breaker tripping,
# backend errors, 5xx responses, and uptime. Declared once at root because it is
# consumed by two different modules (observability and cost-controls) — a
# resource two modules both need has to live where both can reach it.

resource "google_monitoring_notification_channel" "budget_email" {
  project      = var.gcp_project_id
  display_name = "Budget Alert Email"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.required_apis]
}
