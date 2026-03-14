# ─── Cloud Build ──────────────────────────────────────────────────────────────
# Always-free tier: 2,500 build-minutes/mo on e2-standard-2

locals {
  cloudbuild_sa_email = "${data.google_project.project.number}@cloudbuild.gserviceaccount.com"
}

data "google_project" "project" {
  project_id = var.gcp_project_id
}

# Allow Cloud Build to push images to Artifact Registry
resource "google_project_iam_member" "cloudbuild_artifact_registry" {
  project = var.gcp_project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${local.cloudbuild_sa_email}"

  depends_on = [google_project_service.required_apis]
}

# Allow Cloud Build to deploy to Cloud Run
resource "google_project_iam_member" "cloudbuild_run_developer" {
  project = var.gcp_project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${local.cloudbuild_sa_email}"

  depends_on = [google_project_service.required_apis]
}

# Allow Cloud Build to act as the backend service account (for Cloud Run deploy)
resource "google_service_account_iam_member" "cloudbuild_act_as_backend" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.cloudbuild_sa_email}"
}

# Cloud Build trigger (2nd Gen) — fires on push to main branch
resource "google_cloudbuild_trigger" "backend_deploy" {
  project  = var.gcp_project_id
  name     = "mfs-backend-deploy"
  location = var.gcp_region

  depends_on = [google_project_service.required_apis]

  # For regional triggers, the service account must be the full resource name
  service_account = "projects/made-for-seconds/serviceAccounts/${data.google_project.project.number}@cloudbuild.gserviceaccount.com"

  repository_event_config {
    # Full absolute path as confirmed via gcloud
    repository = "projects/made-for-seconds/locations/us-central1/connections/github-connection/repositories/kevin-tran12-MadeForSeconds"
    
    push {
      branch = "^main$"
    }
  }

  filename = "cloudbuild.yaml"

  substitutions = {
    _IMAGE = "us-central1-docker.pkg.dev/made-for-seconds/mfs/backend"
  }
}
