# ─── Cost Protection ──────────────────────────────────────────────────────────
# Budget alert at $1/month with auto-kill via Cloud Function.
# Alerts at 50%, 80%, and 100%. At 100%, a Pub/Sub message triggers a
# Cloud Function that scales Cloud Run to 0 instances.

# ─── Notification channel (email) ────────────────────────────────────────────

resource "google_monitoring_notification_channel" "budget_email" {
  project      = var.gcp_project_id
  display_name = "Budget Alert Email"
  type         = "email"

  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.required_apis]
}

# ─── Pub/Sub topic for budget notifications ──────────────────────────────────

resource "google_pubsub_topic" "budget_alert" {
  project = var.gcp_project_id
  name    = "budget-alert"

  depends_on = [google_project_service.required_apis]
}

# ─── Budget ──────────────────────────────────────────────────────────────────

data "google_billing_account" "account" {
  billing_account = var.billing_account
}

resource "google_billing_budget" "monthly_cap" {
  billing_account = data.google_billing_account.account.id
  display_name    = "MFS Monthly Budget"

  budget_filter {
    projects = ["projects/${var.gcp_project_id}"]
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

  all_updates_rule {
    monitoring_notification_channels = [
      google_monitoring_notification_channel.budget_email.name,
    ]
    pubsub_topic = google_pubsub_topic.budget_alert.id
  }

  depends_on = [google_project_service.required_apis]
}

# ─── Service account for the kill function ───────────────────────────────────

resource "google_service_account" "budget_killer" {
  project      = var.gcp_project_id
  account_id   = "budget-killer"
  display_name = "Budget Killer Cloud Function"
}

# Grant permission to update the Cloud Run service (scale to 0)
resource "google_cloud_run_v2_service_iam_member" "budget_killer_admin" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.budget_killer.email}"
}

# ─── Cloud Function (Gen 2) ─────────────────────────────────────────────────

# Zip the function source for upload
data "archive_file" "budget_killer_source" {
  type        = "zip"
  source_dir  = "${path.module}/billing_function"
  output_path = "${path.module}/.tmp/billing_function.zip"
}

# GCS bucket for function source code
resource "google_storage_bucket" "function_source" {
  project                     = var.gcp_project_id
  name                        = "${var.gcp_project_id}-function-source"
  location                    = var.gcp_region
  uniform_bucket_level_access = true
  force_destroy               = true

  depends_on = [google_project_service.required_apis]
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
      GCP_PROJECT_ID = var.gcp_project_id
      GCP_REGION     = var.gcp_region
    }
  }

  event_trigger {
    trigger_region = var.gcp_region
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.budget_alert.id
    # Retry on failure — this function is the cost backstop; a dropped
    # message must not silently skip the shutdown
    retry_policy = "RETRY_POLICY_RETRY"
  }

  depends_on = [google_project_service.required_apis]
}
