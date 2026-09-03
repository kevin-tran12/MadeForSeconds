output "service_name" {
  description = "Cloud Run service name — consumed by cost-controls (the budget killer acts on it) and by the root-level uptime check"
  value       = google_cloud_run_v2_service.backend.name
}

output "service_uri" {
  description = "Cloud Run service URL"
  value       = google_cloud_run_v2_service.backend.uri
}

output "repository_id" {
  description = "Artifact Registry repository id — the root output builds the full pkg.dev path from this"
  value       = google_artifact_registry_repository.backend.repository_id
}

output "referenced_secret_ids" {
  description = "secret_id of every Secret Manager secret the Cloud Run template injects, optional ones included. Checked against module.security.granted_secret_accessors by terraform/tests/secret_access.tftest.hcl: anything in here without a matching accessor binding makes revision creation fail."
  value       = toset(concat([var.secret_ids.admin_emails], [for entry in local.optional_secret_env : entry.secret_id]))
}

output "assistant_federation_env_names" {
  description = "Names of the Anthropic Workload Identity Federation env vars the Cloud Run template injects for the Sous Chef assistant — empty when the assistant is off. Asserted by terraform/tests/assistant_federation.tftest.hcl."
  value       = toset(keys(local.assistant_federation_env))
}
