# ─── Required GCP APIs ────────────────────────────────────────────────────────
# All APIs must be enabled before other resources can be created.
# Without this, terraform apply fails on a fresh project.

locals {
  required_apis = [
    "run.googleapis.com",
    "firestore.googleapis.com",
    "artifactregistry.googleapis.com",
    "identitytoolkit.googleapis.com",
    "iam.googleapis.com",
    "cloudbuild.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    "logging.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudfunctions.googleapis.com",
    "pubsub.googleapis.com",
    "eventarc.googleapis.com",
    "iamcredentials.googleapis.com", # signed URLs via IAM signBlob (no key file on Cloud Run)
    "monitoring.googleapis.com",     # uptime checks + alert policies
    "cloudscheduler.googleapis.com", # weekly Instagram token refresh
    "cloudtrace.googleapis.com",     # MCP tool-call spans (backend/app/tracing.py)
  ]
}

resource "google_project_service" "required_apis" {
  for_each = toset(local.required_apis)

  project            = var.gcp_project_id
  service            = each.value
  disable_on_destroy = false
}

# Shared project metadata. Declared here rather than beside whichever resource
# happened to need it first — data.google_project.project is consumed by both
# billing.tf (budget_filter's project number, and the pubsub service agent
# email) and, historically, cloudbuild.tf. A data source that lives inside a
# resource's file but is used by a different file becomes a hazard the moment
# either file moves into a module.
data "google_project" "project" {
  project_id = var.gcp_project_id
}
