# ─── Social token refresh: alerts ────────────────────────────────────────────
# The original Instagram refresh job failed on every attempt for weeks with
# nobody noticing (see scheduler.tf). Two alerts close that gap, mirroring the
# secret pruner's pair: one for "the endpoint ran and a platform refresh
# failed" (the application marker), one for "the Scheduler attempt never
# reached the endpoint" (OIDC minting, IAM, routing, cold-start timeout).
# Both exist only alongside the job itself.

resource "google_monitoring_alert_policy" "social_refresh_failure" {
  count   = var.instagram_access_token != "" ? 1 : 0
  project = var.gcp_project_id

  display_name = "Social token refresh: a platform refresh failed"
  severity     = "WARNING"
  combiner     = "OR"

  conditions {
    display_name = "Backend logged SOCIAL_REFRESH_FAILED"

    # The backend logs through google-cloud-logging's handler (structured
    # jsonPayload) in production; textPayload is matched too so a plain
    # stdout line would still count.
    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_run_revision"
        resource.labels.service_name="${google_cloud_run_v2_service.backend.name}"
        (jsonPayload.message:"SOCIAL_REFRESH_FAILED" OR textPayload:"SOCIAL_REFRESH_FAILED")
      EOT
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
  }

  notification_channels = [var.notification_channel]

  documentation {
    content   = <<-EOT
      A social platform's token could not be refreshed. The log line names
      the platform and Meta's/the platform's error text; Firestore
      `config/social` holds the same under `<platform>.last_error`, and the
      MCP `social_status` tool reads it.

      The usual cause is a token that had already expired before the job
      ran (Meta: "Session has expired on …") — a refresh can only extend a
      token that is still valid. Recover by repeating the one-time OAuth
      exchange in docs/DEPLOYMENT.md § Instagram publishing, adding the new
      token as a Secret Manager version, and then running the job by hand
      (`gcloud scheduler jobs run social-token-refresh --location us-central1`)
      so the fresh token is exchanged for a full 60-day one immediately.
    EOT
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "social_refresh_scheduler_failure" {
  count   = var.instagram_access_token != "" ? 1 : 0
  project = var.gcp_project_id

  display_name = "Social token refresh: Scheduler execution failed"
  severity     = "WARNING"
  combiner     = "OR"

  conditions {
    display_name = "Scheduler attempt failed before reaching the backend"

    # UNREACHABLE_5xx means the request reached the backend and it answered
    # 5xx — that case is the application alert above, not this one.
    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_scheduler_job"
        resource.labels.job_id="${google_cloud_scheduler_job.social_token_refresh[0].name}"
        jsonPayload."@type"="type.googleapis.com/google.cloud.scheduler.logging.AttemptFinished"
        severity="ERROR"
        NOT jsonPayload.debugInfo:"UNREACHABLE_5xx"
      EOT
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
  }

  notification_channels = [var.notification_channel]

  documentation {
    content   = <<-EOT
      The Scheduler could not complete its call to the backend's social
      refresh endpoint (OIDC token minting, the backend SA's
      serviceAccountTokenCreator grant to the Scheduler agent, routing, or a
      cold-start timeout). Check
      `gcloud logging read 'resource.type="cloud_scheduler_job" resource.labels.job_id="social-token-refresh"'`
      for the AttemptFinished entry's `status` and `debugInfo`.

      Like the pruner's equivalent, this does not cover a paused job (no
      attempts, no ERROR entry): `gcloud scheduler jobs describe
      social-token-refresh --location us-central1` should say ENABLED.
    EOT
    mime_type = "text/markdown"
  }
}
