# ─── Application error alerting ───────────────────────────────────────────────
# Log-based metrics + alert policies on top of the logging the backend already
# does (google.cloud.logging in main.py) and Cloud Run's automatic per-request
# logs. Both metrics and alert policies are free — only log *ingestion* costs
# anything, and that's already covered by the 50 GiB/mo free tier. Thresholds
# are loose (>5 in 15 min) to avoid paging on a single transient blip for a
# low-traffic personal app, and reuse the existing budget/uptime email channel
# so no new notification channel is needed.

# ─── Error-severity log entries ──────────────────────────────────────────────
# Catches explicit logger.error/logger.exception calls as well as uncaught
# tracebacks written to stderr, which Cloud Run auto-tags as ERROR severity.

resource "google_logging_metric" "backend_errors" {
  project     = var.gcp_project_id
  name        = "backend_errors"
  description = "Count of ERROR+ severity log entries from mfs-backend"

  filter = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="mfs-backend"
    severity>=ERROR
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# Creating a log-based metric registers it with Logging immediately, but the
# Monitoring API only sees the descriptor a few minutes later. Referencing the
# metric from an alert policy in the same apply therefore fails with
# "Cannot find metric(s) that match type = logging.googleapis.com/user/...".
# Terraform's dependency graph is already correct — this is pure GCP eventual
# consistency, so the only fix is to wait.
#
# time_sleep delays on create only, so this costs nothing on subsequent applies
# and nothing at all once the policies exist. If a from-scratch apply still
# races (GCP documents up to 10 minutes), re-running apply is safe and picks up
# exactly where it left off.
resource "time_sleep" "wait_for_log_metrics" {
  depends_on = [
    google_logging_metric.backend_errors,
    google_logging_metric.backend_5xx,
  ]

  create_duration = "180s"
}

resource "google_monitoring_alert_policy" "backend_errors" {
  project      = var.gcp_project_id
  display_name = "MFS backend errors"
  combiner     = "OR"

  depends_on = [time_sleep.wait_for_log_metrics]

  conditions {
    display_name = "Error log entries"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND metric.type = \"logging.googleapis.com/user/${google_logging_metric.backend_errors.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "0s"

      aggregations {
        alignment_period     = "900s"
        per_series_aligner   = "ALIGN_COUNT"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [var.notification_channel]
}

# ─── HTTP 5xx responses ───────────────────────────────────────────────────────
# Cloud Run writes a request log entry per HTTP request automatically. This
# catches handled code paths that return a 500 without going through
# logger.error (e.g. an HTTPException(500, ...) raised without logging).

resource "google_logging_metric" "backend_5xx" {
  project     = var.gcp_project_id
  name        = "backend_5xx"
  description = "Count of HTTP 5xx responses from mfs-backend"

  filter = <<-EOT
    resource.type="cloud_run_revision"
    resource.labels.service_name="mfs-backend"
    httpRequest.status>=500
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_monitoring_alert_policy" "backend_5xx" {
  project      = var.gcp_project_id
  display_name = "MFS backend 5xx responses"
  combiner     = "OR"

  depends_on = [time_sleep.wait_for_log_metrics]

  conditions {
    display_name = "5xx request log entries"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND metric.type = \"logging.googleapis.com/user/${google_logging_metric.backend_5xx.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "0s"

      aggregations {
        alignment_period     = "900s"
        per_series_aligner   = "ALIGN_COUNT"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [var.notification_channel]
}
