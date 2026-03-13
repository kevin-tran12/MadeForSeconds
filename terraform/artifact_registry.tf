# ─── Artifact Registry (Docker images) ────────────────────────────────────────

resource "google_artifact_registry_repository" "backend" {
  project       = var.gcp_project_id
  location      = var.gcp_region
  repository_id = "mfs"
  format        = "DOCKER"
  description   = "MadeForSeconds backend Docker images"
}
