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
