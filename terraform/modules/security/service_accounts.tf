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

# Write access for the MCP tool-call spans app/tracing.py exports via
# CloudTraceSpanExporter (roles/cloudtrace.agent is the write-only trace
# role — no read access, matching logWriter's shape above).
resource "google_project_iam_member" "backend_trace" {
  project = var.gcp_project_id
  role    = "roles/cloudtrace.agent"
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

# ─── Service Account for the build/deploy pipeline ─────────────────────────────
#
# .github/workflows/deploy.yml (PR 10) authenticates as this identity via WIF
# to build, push, and promote the backend image — Cloud Build's own
# push-triggered trigger (formerly modules/backend-service/cloudbuild.tf, also
# run as this SA) is retired as of that PR, since a second independent
# push-triggered deploy path racing the GitHub Actions pipeline would be a bug
# waiting to happen, not a feature. mfs-backend carried build permissions
# it had no business holding outside a build: a compromised dependency or a
# merged build-script change inherited Firestore read/write, a role on the
# receipts bucket, every secretAccessor grant above, and signBlob — none of
# which a build step that only needs to push an image and deploy it should be
# able to touch. (The receipts-bucket role itself was later narrowed from
# objectAdmin to get+create-only, mfsReceiptsUploader — Epic 2, story 2.2,
# see modules/storage/buckets.tf — but the isolation argument here doesn't
# depend on which role it is, only on mfs-deploy needing none of it.)
#
# mfs-backend's matching build-time grants and its actAs-on-self binding are
# gone as of Epic 2 (2.1) — `gcloud builds list` showed 8 consecutive SUCCESS
# runs under this trigger as mfs-deploy before they were removed, confirming
# nothing outside a build ever depended on mfs-backend holding them.
resource "google_service_account" "deploy" {
  project      = var.gcp_project_id
  account_id   = "mfs-deploy"
  display_name = "MadeForSeconds Cloud Build Deploy"
}

# Artifact Registry push access and Cloud Run deploy access both live in
# modules/backend-service/deploy_iam.tf instead of here (Epic 2, story 2.2) —
# resource-scoped to the mfs repo and mfs-backend's own Cloud Run service via
# a custom role, not project-wide roles/artifactregistry.writer /
# roles/run.developer as before. That module owns both resources, so the
# bindings live with what they grant on, per this repo's IAM convention;
# security stays responsible for creating the identity and exposing it.

# A build-provided service account must write its own build logs — cloudbuild.yaml
# sets options.logging = CLOUD_LOGGING_ONLY, which requires this on any
# non-default service account, not just the default Cloud Build one.
resource "google_project_iam_member" "deploy_logging" {
  project = var.gcp_project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.deploy.email}"
}

# actAs: deploying a Cloud Run revision that runs as mfs-backend requires the
# deployer to be allowed to act as that identity. mfs-backend no longer holds
# this grant on itself (removed alongside its other build-time permissions in
# Epic 2, story 2.1) — mfs-deploy is the only identity that needs it now.
resource "google_service_account_iam_member" "deploy_act_as_backend" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deploy.email}"
}
