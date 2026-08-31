# ─── mfs-deploy: resource-scoped deploy access ─────────────────────────────────
# Epic 2, story 2.2. roles/run.developer (the predefined role mfs-deploy held
# until now) grants ~90 permissions — Jobs, WorkerPools, Executions, instance
# SSH, IAM-policy read, Recommender insights — none of which the deploy
# pipeline's three gcloud calls (`run deploy --no-traffic --tag=candidate`,
# `run services describe`, `run services update-traffic` — originally
# cloudbuild.yaml's, now .github/workflows/deploy.yml's as of PR 10, running
# under this same mfs-deploy identity via WIF instead of Cloud Build's
# built-in trigger identity) touch. It was also bound at the project level,
# so mfs-deploy could reach every Cloud Run service in the project,
# including the budget-killer/resetter functions (Gen2 functions run on
# Cloud Run infrastructure) — no legitimate reason to touch those.
#
# Both bindings below are scoped to the one resource mfs-deploy actually
# deploys, and the custom role starts from the documented minimum for
# updating an existing Cloud Run service, widened only on a proven 403 from a
# real build. If the deploy pipeline ever needs Jobs, WorkerPools, or a second
# service, that is a deliberate decision to make then, not a permission that
# was already sitting there unused.

resource "google_project_iam_custom_role" "cloud_run_deployer" {
  project     = var.gcp_project_id
  role_id     = "mfsCloudRunDeployer"
  title       = "MFS Cloud Run Deployer"
  description = "Minimum permissions to deploy a candidate revision and shift traffic on mfs-backend's own Cloud Run service — see deploy_iam.tf"

  permissions = [
    "run.services.get",    # `run services describe` (smoke-test step)
    "run.services.update", # `run deploy --no-traffic` and `update-traffic` are both service updates
    "run.operations.get",  # polling the long-running operation each of the above starts
  ]
}

resource "google_cloud_run_v2_service_iam_member" "deploy_run_deployer" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = google_cloud_run_v2_service.backend.name
  role     = google_project_iam_custom_role.cloud_run_deployer.id
  member   = "serviceAccount:${var.deploy_sa_email}"
}

resource "google_artifact_registry_repository_iam_member" "deploy_artifact_registry" {
  project    = var.gcp_project_id
  location   = var.gcp_region
  repository = google_artifact_registry_repository.backend.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${var.deploy_sa_email}"
}
