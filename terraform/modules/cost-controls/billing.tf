# ─── Cost Protection ──────────────────────────────────────────────────────────
# Budget alert at $1/month with auto-kill via Cloud Function.
# Alerts at 50%, 80%, and 100%. At 100%, a Pub/Sub message triggers a
# Cloud Function that scales Cloud Run to 0 instances.

# ─── Pub/Sub topic for budget notifications ──────────────────────────────────

resource "google_pubsub_topic" "budget_alert" {
  project = var.gcp_project_id
  name    = "budget-alert"
}

# Grant the Cloud Billing Budgets service agent permission to publish to this
# topic. GCP auto-creates this binding when the budget is associated with the
# topic, but without this resource Terraform would silently drop it if the
# topic is ever recreated.
resource "google_pubsub_topic_iam_member" "budget_alert_publisher" {
  project = var.gcp_project_id
  topic   = google_pubsub_topic.budget_alert.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:billing-budget-alert@system.gserviceaccount.com"
}

# ─── Budget ──────────────────────────────────────────────────────────────────

data "google_billing_account" "account" {
  billing_account = var.billing_account
}

resource "google_billing_budget" "monthly_cap" {
  billing_account = data.google_billing_account.account.id
  display_name    = "MFS Monthly Budget"

  budget_filter {
    # Project NUMBER, not ID. The Budget API always returns the number, so
    # "projects/${var.gcp_project_id}" never matches what comes back and every
    # plan shows the same diff — applying it does not converge, it just re-queues
    # itself. data.google_project.project is declared once in apis.tf and shared with the pubsub grant below.
    projects = ["projects/${var.project_number}"]
  }

  amount {
    specified_amount {
      currency_code = "USD"
      units         = tostring(var.monthly_budget_amount)
    }
  }

  # 50% — early warning email
  threshold_rules {
    threshold_percent = 0.5
    spend_basis       = "CURRENT_SPEND"
  }

  # 80% — stronger warning email
  threshold_rules {
    threshold_percent = 0.8
    spend_basis       = "CURRENT_SPEND"
  }

  # 100% — email + Pub/Sub (triggers kill function)
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "CURRENT_SPEND"
  }

  # Forecasted 100% — early warning only. GCP projects month-end spend from the
  # current run rate, so this lands days before actual spend confirms, which
  # matters because billing data itself lags by hours. This does NOT kill:
  # kill_cloud_run compares *actual* costAmount, still under budget here.
  threshold_rules {
    threshold_percent = 1.0
    spend_basis       = "FORECASTED_SPEND"
  }

  all_updates_rule {
    monitoring_notification_channels = [
      var.notification_channel,
    ]
    pubsub_topic = google_pubsub_topic.budget_alert.id
  }
}

# ─── Service account for the kill function ───────────────────────────────────

resource "google_service_account" "budget_killer" {
  project      = var.gcp_project_id
  account_id   = "budget-killer"
  display_name = "Budget Killer Cloud Function"
}

# The breaker trips by revoking the service's public invoker binding, which needs
# getIamPolicy/setIamPolicy on the service — run.developer does not include
# setIamPolicy, so this is run.admin, scoped to the one service.
#
# This replaces an earlier design that called update_service to set
# max_instance_count = 0. That required run.developer on the service *plus*
# artifactregistry.reader on the image repo (the API re-resolves the image
# against the caller) *plus* iam.serviceAccountUser on the runtime SA (the
# service runs as it) *plus* run.operations.get to poll the result. Every one of
# those was missing, surfaced one at a time, and each produced the same silent
# failure: the breaker logged success, emailed, and changed nothing. Worse, the
# mechanism itself did not work — see the module docstring in
# billing_function/main.py. Revoking invoker needs exactly this one grant.
resource "google_cloud_run_v2_service_iam_member" "budget_killer_admin" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = var.backend_service_name
  role     = "roles/run.admin"
  member   = "serviceAccount:${google_service_account.budget_killer.email}"
}

# ─── Cloud Function (Gen 2) ─────────────────────────────────────────────────

# Zip the function source for upload.
#
# output_file_mode is what makes the archive reproducible across machines.
# Without it the provider records each file's real mode, and Windows has no Unix
# permissions — Go reports 0666 there against 0644 on macOS and Linux. Different
# mode bits produce different zip bytes, so output_md5 differs, which renames the
# source object and forces BOTH Cloud Functions to redeploy. That happened on
# every switch between machines, for no functional change to the code.
#
# Timestamps are already normalised by the provider (it stamps 2049-01-01), so
# mode was the only remaining source of drift.
data "archive_file" "budget_killer_source" {
  type             = "zip"
  source_dir       = "${path.module}/billing_function"
  output_path      = "${path.module}/.tmp/billing_function.zip"
  output_file_mode = "0644"
}

# GCS bucket for function source code
resource "google_storage_bucket" "function_source" {
  project                     = var.gcp_project_id
  name                        = "${var.gcp_project_id}-function-source"
  location                    = var.gcp_region
  uniform_bucket_level_access = true
  force_destroy               = true
}

resource "google_storage_bucket_object" "budget_killer_source" {
  name   = "billing_function-${data.archive_file.budget_killer_source.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.budget_killer_source.output_path
}

resource "google_cloudfunctions2_function" "budget_killer" {
  project  = var.gcp_project_id
  name     = "budget-killer"
  location = var.gcp_region

  build_config {
    runtime     = "python312"
    entry_point = "kill_cloud_run"

    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.budget_killer_source.name
      }
    }
  }

  service_config {
    max_instance_count = 1
    available_memory   = "256Mi"
    timeout_seconds    = 60

    service_account_email = google_service_account.budget_killer.email

    environment_variables = {
      GCP_PROJECT_ID    = var.gcp_project_id
      GCP_REGION        = var.gcp_region
      CLOUD_RUN_SERVICE = var.backend_service_name
    }
  }

  event_trigger {
    trigger_region        = var.gcp_region
    event_type            = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic          = google_pubsub_topic.budget_alert.id
    service_account_email = google_service_account.budget_killer.email
    # Retry on failure — this function is the cost backstop; a dropped
    # message must not silently skip the shutdown
    retry_policy = "RETRY_POLICY_RETRY"
  }
}

# ─── IAM for Eventarc custom trigger SA ──────────────────────────────────────
# Three grants are required when pinning a custom SA on a Pub/Sub event trigger.
# All three must be present or Pub/Sub push delivery fails silently.

# 1. Custom SA must be able to invoke the function's own backing Cloud Run service.
resource "google_cloud_run_v2_service_iam_member" "budget_killer_invoker" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = "budget-killer"
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.budget_killer.email}"

  depends_on = [google_cloudfunctions2_function.budget_killer]
}

# 2. Custom SA must be able to receive Eventarc events.
resource "google_project_iam_member" "budget_killer_eventarc" {
  project = var.gcp_project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.budget_killer.email}"
}

# 3. Pub/Sub service agent must be able to mint tokens as the custom SA so it
#    can authenticate push delivery to the Cloud Run backing service.
#    Uses data.google_project.project from cloudbuild.tf — no duplicate data source.
resource "google_service_account_iam_member" "pubsub_token_creator" {
  service_account_id = google_service_account.budget_killer.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

# ─── Breaker reset function ──────────────────────────────────────────────────
# The budget resets on the 1st of the month, but max_instance_count = 0 does not.
# Without this the site stays down until someone notices and runs terraform.
#
# Deployed from the SAME source zip as budget-killer — one archive, two entry
# points. Runs as the budget_killer SA, which already holds exactly the
# roles/run.developer grant this needs (see budget_killer_admin above); a
# separate SA would need an identical grant for no isolation benefit.

resource "google_cloudfunctions2_function" "budget_resetter" {
  project  = var.gcp_project_id
  name     = "budget-resetter"
  location = var.gcp_region

  build_config {
    runtime     = "python312"
    entry_point = "reset_cloud_run"

    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.budget_killer_source.name
      }
    }
  }

  service_config {
    max_instance_count = 1
    available_memory   = "256Mi"
    timeout_seconds    = 60

    service_account_email = google_service_account.budget_killer.email

    # Scheduler authenticates with an OIDC token; no unauthenticated access.
    ingress_settings = "ALLOW_ALL"

    environment_variables = {
      GCP_PROJECT_ID    = var.gcp_project_id
      GCP_REGION        = var.gcp_region
      CLOUD_RUN_SERVICE = var.backend_service_name
    }
  }
}

# The scheduler job presents an OIDC token as the budget_killer SA, so that SA
# must be able to invoke the resetter's own backing Cloud Run service.
resource "google_cloud_run_v2_service_iam_member" "budget_resetter_invoker" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = "budget-resetter"
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.budget_killer.email}"

  depends_on = [google_cloudfunctions2_function.budget_resetter]
}

# Cloud Scheduler's service agent must be able to mint OIDC tokens as the
# budget_killer SA. The equivalent grant in scheduler.tf covers the backend SA
# only, so this is a separate binding.
resource "google_service_account_iam_member" "scheduler_mints_budget_killer_oidc" {
  service_account_id = google_service_account.budget_killer.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${var.scheduler_agent_email}"
}

# ─── Breaker-tripped alert ───────────────────────────────────────────────────
# Scaling to 0 also trips the generic "MFS backend down" uptime alert, which
# looks identical to a real outage. This fires on the kill function's log marker
# so the cause is unambiguous — and so you don't terraform apply the breaker off
# without knowing why it tripped.

resource "google_monitoring_alert_policy" "budget_breaker_tripped" {
  project = var.gcp_project_id

  # GCP composes the notification subject as
  #   [ALERT - <severity>] <display_name> for <resource> with {<labels>}
  # The resource/label suffix is not suppressible, so keep display_name short —
  # a long one pushes the meaning off the end of a phone notification. Setting
  # severity replaces the default "[ALERT - No severity]" prefix.
  display_name = "MFS site DOWN — budget cap hit"
  severity     = "CRITICAL"
  combiner     = "OR"

  conditions {
    display_name = "Budget breaker scaled the backend to zero"

    # Gen2 functions log under cloud_run_revision, not cloud_function.
    # Marker string is defined as TRIPPED_MARKER in billing_function/main.py.
    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_run_revision"
        resource.labels.service_name="${google_cloudfunctions2_function.budget_killer.name}"
        textPayload:"BUDGET_BREAKER_TRIPPED"
      EOT
    }
  }

  # Required by the API for log-match conditions.
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
  }

  notification_channels = [var.notification_channel]

  documentation {
    content   = <<-EOT
      The monthly budget cap was exceeded and ${var.backend_service_name}
      has been scaled to 0 instances. The site is DOWN.

      Investigate the spend before restoring. To restore early:
        gcloud scheduler jobs run budget-breaker-reset --location ${var.gcp_region} --project ${var.gcp_project_id}

      Otherwise it restores automatically on the 1st at 08:00 UTC.
    EOT
    mime_type = "text/markdown"
  }
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
    google_cloud_run_v2_service_iam_member.budget_resetter_invoker,
    google_service_account_iam_member.scheduler_mints_budget_killer_oidc,
  ]
}
