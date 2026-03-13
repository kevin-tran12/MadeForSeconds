# ─── Cloud Build ──────────────────────────────────────────────────────────────
# Always-free tier: 2,500 build-minutes/mo on e2-standard-2
#
# PREREQUISITE (2nd Gen):
# 1. Go to GCP Console -> Cloud Build -> Repositories (2nd Gen)
# 2. Create a connection named "github-connection"
# 3. Link your "MadeForSeconds" repository inside that connection.

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

  repository_event_config {
    # 2nd Gen uses a specific repository resource ID.
    # Format: projects/PROJECT_ID/locations/REGION/connections/CONNECTION_NAME/repositories/REPO_ID
    repository = "projects/${var.gcp_project_id}/locations/${var.gcp_region}/connections/github-connection/repositories/${var.github_owner}-${var.github_repo}"
    
    push {
      branch = "^main$"
    }
  }

  filename = "cloudbuild.yaml"

  substitutions = {
    _IMAGE = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project_id}/${google_artifact_registry_repository.backend.repository_id}/backend"
  }
}
