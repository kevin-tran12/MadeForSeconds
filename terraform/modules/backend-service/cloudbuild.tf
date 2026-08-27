# ─── Cloud Build ──────────────────────────────────────────────────────────────
# Always-free tier: 2,500 build-minutes/mo on default machine
#
# The trigger below runs as mfs-deploy (modules/security/service_accounts.tf),
# not mfs-backend — mfs-backend is the Cloud Run runtime identity, and it holds
# Firestore read/write, the receipts bucket's objectAdmin, every
# secretAccessor grant, and signBlob. A compromised dependency or a merged
# build-script change had no business inheriting any of that just to push an
# image and deploy it, which mfs-deploy's narrower grants (artifactregistry.
# writer, run.developer, its own logWriter, and actAs on mfs-backend) are
# scoped to.
#
# mfs-backend's own cloudbuild_artifact_registry / cloudbuild_run_developer
# grants below are deliberately UNCHANGED in this PR, even though this trigger
# no longer runs as that identity and so no longer needs them. Removing them
# now would make this apply able to break the deploy pipeline if mfs-deploy
# turns out to be missing something — there is no live run to test it against
# from this environment. They come out in a follow-up PR, once a real push to
# main has been observed building, pushing, and deploying successfully under
# mfs-deploy.

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

  service_account = var.deploy_sa_id

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
