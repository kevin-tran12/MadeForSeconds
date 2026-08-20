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
