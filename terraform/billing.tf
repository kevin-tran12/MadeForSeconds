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
    trigger_region        = var.gcp_region
    event_type            = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic          = google_pubsub_topic.budget_alert.id
    service_account_email = google_service_account.budget_killer.email
    # Retry on failure — this function is the cost backstop; a dropped
    # message must not silently skip the shutdown
    retry_policy = "RETRY_POLICY_RETRY"
  }

  depends_on = [google_project_service.required_apis]
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
  member             = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}
