# ─── Cloud Build ──────────────────────────────────────────────────────────────
# Always-free tier: 2,500 build-minutes/mo on default machine

# Allow Cloud Build (running as mfs-backend SA) to push images to Artifact Registry
resource "google_project_iam_member" "cloudbuild_artifact_registry" {
  project = var.gcp_project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${var.backend_sa_email}"
}

# Allow Cloud Build (running as mfs-backend SA) to deploy to Cloud Run
resource "google_project_iam_member" "cloudbuild_run_developer" {
  project = var.gcp_project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${var.backend_sa_email}"
}

# Cloud Build trigger (2nd Gen) — fires on push to main branch
resource "google_cloudbuild_trigger" "backend_deploy" {
  project  = var.gcp_project_id
  name     = "mfs-backend-deploy"
  location = var.gcp_region

  service_account = var.backend_sa_id

  repository_event_config {
    # Full absolute path as confirmed via gcloud
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
