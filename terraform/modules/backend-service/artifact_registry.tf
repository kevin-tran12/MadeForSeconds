# ─── Artifact Registry (Docker images) ────────────────────────────────────────
# Always-free tier: 0.5 GB storage/mo
# Cleanup policy keeps storage under the free limit.
#
# Evaluation order matters here: Artifact Registry always applies KEEP policies
# before DELETE ones, so keep-recent-tagged fixes which var.ar_keep_count
# versions are protected first, and delete-old-tagged then removes every other
# tagged version. Without a DELETE policy matching TAGGED images, old tagged
# images accumulated forever — keep-recent-tagged alone only ever protected
# versions, it never deleted anything.

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
      keep_count = var.ar_keep_count
    }
  }

  cleanup_policies {
    id     = "delete-old-tagged"
    action = "DELETE"
    condition {
      tag_state = "TAGGED"
    }
  }
}
