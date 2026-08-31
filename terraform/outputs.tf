output "cloud_run_url" {
  description = "Cloud Run service URL"
  value       = module.backend-service.service_uri
}

output "artifact_registry_repo" {
  description = "Artifact Registry repository path"
  value       = "${var.gcp_region}-docker.pkg.dev/${var.gcp_project_id}/${module.backend-service.repository_id}"
}

output "service_account_email" {
  description = "Backend service account email"
  value       = module.security.backend_sa_email
}

output "deploy_service_account_email" {
  description = "Cloud Build deploy service account email — what the mfs-backend-deploy trigger runs as"
  value       = module.security.deploy_sa_email
}

output "workload_identity_provider" {
  description = "Full resource name of the GitHub Actions WIF provider — the WIF_PROVIDER GitHub Actions repo variable value. Read with: terraform output -raw workload_identity_provider"
  value       = module.security.workload_identity_provider
}

output "terraform_service_account_email" {
  description = "mfs-terraform's email — the WIF_SERVICE_ACCOUNT GitHub Actions repo variable value. Read with: terraform output -raw terraform_service_account_email"
  value       = module.security.terraform_sa_email
}

# ─── Secret wiring ────────────────────────────────────────────────────────────
# Cloud Run rejects a revision that references a secret its service identity
# cannot read, so these two are worth being able to read straight off the state
# rather than reconstructing by hand from two modules. Asserted in
# terraform/tests/secret_access.tftest.hcl; also usable as a standing check:
#   terraform output secrets_missing_accessor   # must always be []
#
# Both sides normalized to the terminal secret id ("admin-emails") before
# comparing. Every resource here is *configured* with that short form, but on
# a live plan against already-applied state, an existing
# google_secret_manager_secret_iam_member resource can refresh secret_id back
# from the real API as the fully qualified projects/P/secrets/NAME form —
# observed specifically for admin-emails and redis-url, the two bindings that
# pre-date this PR and are migrated in place via moved.tf rather than freshly
# created. Comparing the raw values then reports a working, already-granted
# binding as missing. regex() strips whichever prefix (if any) either side's
# provider happens to echo back, so the comparison is representation-agnostic
# regardless of which side normalizes and which doesn't — see
# terraform/tests/secret_access.tftest.hcl's already_qualified_accessor_names_
# still_match run for the regression this guards.
locals {
  secrets_injected_into_cloud_run = toset([
    for id in module.backend-service.referenced_secret_ids : regex("[^/]+$", id)
  ])
  secrets_granted_accessor = toset([
    for id in module.security.granted_secret_accessors : regex("[^/]+$", id)
  ])
}

output "secrets_injected_into_cloud_run" {
  description = "Every Secret Manager secret the Cloud Run template reads, optional features included, normalized to its terminal id"
  value       = local.secrets_injected_into_cloud_run
}

output "secrets_missing_accessor" {
  description = "Secrets Cloud Run injects that the runtime service account cannot read, after normalizing away any short-name/fully-qualified-name mismatch between how each side's resource happens to report itself. Any entry here is a revision that will fail to start — this must be empty."
  value       = setsubtract(local.secrets_injected_into_cloud_run, local.secrets_granted_accessor)
}

output "secret_pruner_canary_id" {
  description = "secret_id of the disposable canary secret used to validate secret-pruner's recovery drill (docs/DEPLOYMENT.md § Secret version pruning) without touching a real application secret. null in staging, where module.secret-maintenance doesn't exist."
  value       = try(module.secret-maintenance[0].canary_secret_id, null)
}
