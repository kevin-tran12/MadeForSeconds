# ─── Artifact Registry (Docker images) ────────────────────────────────────────
# Always-free tier: 0.5 GB storage/mo
# Cleanup policy keeps storage under the free limit.

resource "google_artifact_registry_repository" "backend" {
  project       = var.gcp_project_id
  location      = var.gcp_region
  repository_id = "mfs"
  format        = "DOCKER"
  description   = "MadeForSeconds backend Docker images"

  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "86400s" # 1 day
    }
  }

  cleanup_policies {
    id     = "keep-recent-tagged"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }
}
