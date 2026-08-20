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

# ─── Secret wiring ────────────────────────────────────────────────────────────
# Cloud Run rejects a revision that references a secret its service identity
# cannot read, so these two are worth being able to read straight off the state
# rather than reconstructing by hand from two modules. Asserted in
# terraform/tests/secret_access.tftest.hcl; also usable as a standing check:
#   terraform output secrets_missing_accessor   # must always be []

output "secrets_injected_into_cloud_run" {
  description = "Every Secret Manager secret the Cloud Run template reads, optional features included"
  value       = module.backend-service.referenced_secret_ids
}

output "secrets_missing_accessor" {
  description = "Secrets Cloud Run injects that the runtime service account cannot read. Any entry here is a revision that will fail to start — this must be empty."
  value       = setsubtract(module.backend-service.referenced_secret_ids, module.security.granted_secret_accessors)
}
