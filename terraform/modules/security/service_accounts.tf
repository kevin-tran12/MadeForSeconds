# ─── Service Account for Cloud Run ────────────────────────────────────────────

resource "google_service_account" "backend" {
  project      = var.gcp_project_id
  account_id   = "mfs-backend"
  display_name = "MadeForSeconds Backend"
}

# Grant Firestore access
resource "google_project_iam_member" "backend_firestore" {
  project = var.gcp_project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Grant Cloud Logging access
resource "google_project_iam_member" "backend_logging" {
  project = var.gcp_project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Read access — needed to aggregate request logs into the weekly usage report
resource "google_project_iam_member" "backend_logging_viewer" {
  project = var.gcp_project_id
  role    = "roles/logging.viewer"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Read access on every secret this module creates — scoped per secret, never
# project-wide. Cloud Run requires the service identity to hold
# roles/secretmanager.secretAccessor on each secret a revision references, or
# the revision is rejected at creation and the service never starts.
#
# for_each over local.existing_secrets rather than one block per secret: see
# secrets.tf for the drift this replaces. A secret added to that map from now
# on gets its binding without anyone having to remember.
resource "google_secret_manager_secret_iam_member" "backend_secret_access" {
  for_each = local.existing_secrets

  project   = var.gcp_project_id
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

# Dead as of the Cloud Build deploy identity below: this existed so Cloud
# Build, then running as mfs-backend, could deploy Cloud Run services that
# also run as mfs-backend — actAs on itself. The trigger now runs as
# mfs-deploy instead, which holds the same actAs grant on mfs-backend
# (deploy_act_as_backend below) — this one has no remaining consumer. Left in
# place for the same reason cloudbuild.tf's matching grants are: removing it
# now would make this apply able to break the deploy pipeline with no live run
# in this environment to test it against. Removed together with those in the
# follow-up PR, once a real push to main is observed succeeding under
# mfs-deploy.
resource "google_service_account_iam_member" "backend_act_as_self" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.backend.email}"
}

# Allow the backend to sign GCS URLs via the IAM signBlob API. Cloud Run
# metadata credentials have no private key, so generate_signed_url must call
# iamcredentials.signBlob as the SA itself.
resource "google_service_account_iam_member" "backend_token_creator" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.backend.email}"
}

# Let the operator impersonate the backend SA (via `gcloud auth
# application-default login --impersonate-service-account`) so operational
# scripts — e.g. backend/scripts/smoke_test_image_pipeline.py — exercise the
# real backend SA's IAM instead of the operator's own, typically broader,
# credentials. Without this, the smoke test can pass even when the deployed
# revision itself would fail for lack of a grant only the backend SA needs.
resource "google_service_account_iam_member" "backend_operator_impersonation" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "user:${var.state_admin_email}"
}

# Instagram token: the backend reads the latest version at runtime — covered by
# backend_secret_access above like every other secret — and writes refreshed
# versions during rotation, which is this grant. versionAdder is genuinely
# Instagram-only, so it stays a block of its own.
resource "google_secret_manager_secret_iam_member" "backend_instagram_token_adder" {
  count     = var.instagram_access_token != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = google_secret_manager_secret.instagram_access_token[0].secret_id
  role      = "roles/secretmanager.secretVersionAdder"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

# ─── Service Account for Cloud Build ───────────────────────────────────────────
#
# The Cloud Build trigger (modules/backend-service/cloudbuild.tf) now runs as
# this identity instead of mfs-backend. mfs-backend carried build permissions
# it had no business holding outside a build: a compromised dependency or a
# merged build-script change inherited Firestore read/write, the receipts
# bucket's objectAdmin, every secretAccessor grant above, and signBlob — none
# of which a build step that only needs to push an image and deploy it should
# be able to touch.
#
# mfs-backend's matching build-time grants stay in place for now — see
# cloudbuild.tf for why removing them is a separate, follow-up change rather
# than part of this one.
resource "google_service_account" "deploy" {
  project      = var.gcp_project_id
  account_id   = "mfs-deploy"
  display_name = "MadeForSeconds Cloud Build Deploy"
}

# Push the image Cloud Build builds.
resource "google_project_iam_member" "deploy_artifact_registry" {
  project = var.gcp_project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

# Deploy the pushed image to Cloud Run.
resource "google_project_iam_member" "deploy_run_developer" {
  project = var.gcp_project_id
  role    = "roles/run.developer"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

# A build-provided service account must write its own build logs — cloudbuild.yaml
# sets options.logging = CLOUD_LOGGING_ONLY, which requires this on any
# non-default service account, not just the default Cloud Build one.
resource "google_project_iam_member" "deploy_logging" {
  project = var.gcp_project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

# actAs: deploying a Cloud Run revision that runs as mfs-backend requires the
# deployer to be allowed to act as that identity — the same requirement
# backend_act_as_self grants mfs-backend on itself today, moved to the
# identity that will actually need it once the cutover lands.
resource "google_service_account_iam_member" "deploy_act_as_backend" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}
