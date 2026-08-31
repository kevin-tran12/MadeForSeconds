# ─── Cloud Build ──────────────────────────────────────────────────────────────
# Always-free tier: 2,500 build-minutes/mo on default machine
#
# The trigger below runs as mfs-deploy (modules/security/service_accounts.tf),
# not mfs-backend — mfs-backend is the Cloud Run runtime identity, and it holds
# Firestore read/write, a get+create-only role on the receipts bucket
# (mfsReceiptsUploader — narrowed from objectAdmin in Epic 2, story 2.2),
# every secretAccessor grant, and signBlob. A compromised dependency or a
# merged build-script change had no business inheriting any of that just to
# push an image and deploy it, which mfs-deploy's narrower grants are scoped
# to: artifactregistry.writer on the mfs repository specifically, a
# resource-scoped custom role (mfsCloudRunDeployer, see deploy_iam.tf) on
# mfs-backend's own Cloud Run service, its own logWriter, and actAs on
# mfs-backend.
#
# mfs-backend's own cloudbuild_artifact_registry / cloudbuild_run_developer
# grants used to live here too, kept deliberately in place until a real push
# to main was observed succeeding under mfs-deploy. `gcloud builds list`
# showed 8 consecutive SUCCESS runs under this trigger before they were
# removed (Epic 2, story 2.1) — confirmed dead, not just presumed dead.

# Cloud Build trigger (2nd Gen) — fires on push to main branch.
#
# Production only. Two independent reasons, discovered together while
# bootstrapping staging (Epic 8, PR 6):
#   1. A Cloud Build 2nd-gen trigger needs a google_cloudbuild_v2_connection
#      wired to a GitHub App installation, which requires an interactive
#      OAuth consent step Terraform cannot perform — there is no
#      declarative path to create one from scratch per project.
#   2. It would be redundant even if it could be created: once the
#      merge-to-main promotion pipeline exists (PR 10), GitHub Actions is
#      what builds the image and deploys it to both environments — a
#      second, independent push-triggered deploy path racing against that
#      pipeline is a bug waiting to happen, not a feature. Production keeps
#      this trigger only because retiring it is PR 10's job, not this one's.
resource "google_cloudbuild_trigger" "backend_deploy" {
  count = var.deployment_target == "production" ? 1 : 0

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
