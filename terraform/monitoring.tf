# ─── Uptime monitoring ────────────────────────────────────────────────────────
# Synthetic check against /api/health so silent outages page the owner instead
# of waiting for a visitor to notice. 15-minute period keeps the wake-up cost
# of the scale-to-zero service negligible (~96 requests/day).

resource "google_monitoring_uptime_check_config" "backend_health" {
  project      = var.gcp_project_id
  display_name = "MFS backend /api/health"
  timeout      = "10s"
  period       = "900s"

  http_check {
    path         = "/api/health"
    port         = 443
    use_ssl      = true
    validate_ssl = true
  }

  monitored_resource {
    type = "uptime_url"
    labels = {
      project_id = var.gcp_project_id
      host       = replace(google_cloud_run_v2_service.backend.uri, "https://", "")
    }
  }

  depends_on = [google_project_service.required_apis]
}

resource "google_monitoring_alert_policy" "backend_uptime" {
  project      = var.gcp_project_id
  display_name = "MFS backend down"
  combiner     = "OR"

  conditions {
    display_name = "Uptime check failing"

    condition_threshold {
      filter          = "resource.type = \"uptime_url\" AND metric.type = \"monitoring.googleapis.com/uptime_check/check_passed\" AND metric.labels.check_id = \"${google_monitoring_uptime_check_config.backend_health.uptime_check_id}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 1
      duration        = "1200s"

      aggregations {
        alignment_period     = "1200s"
        per_series_aligner   = "ALIGN_NEXT_OLDER"
        cross_series_reducer = "REDUCE_COUNT_FALSE"
        group_by_fields      = ["resource.label.*"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.budget_email.name]
}
