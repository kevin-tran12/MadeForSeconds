# ─── Terraform remote state ───────────────────────────────────────────────────
# Versioned GCS bucket for terraform.tfstate. Local state is a single point of
# failure (laptop loss = state loss) and may contain secret material.
#
# One-time migration after this bucket exists:
#   1. terraform apply                      # creates the bucket (state still local)
#   2. Uncomment the backend block below
#   3. terraform init -migrate-state        # copies local state into the bucket
#   4. Delete terraform.tfstate* locally once verified
#
# The backend block cannot use variables — the bucket name is hardcoded.

# terraform {
#   backend "gcs" {
#     bucket = "made-for-seconds-tf-state"
#     prefix = "terraform/state"
#   }
# }

resource "google_storage_bucket" "tf_state" {
  project  = var.gcp_project_id
  name     = "${var.gcp_project_id}-tf-state"
  location = "US"

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  # Keep history bounded — old state versions beyond 20 are pruned
  lifecycle_rule {
    condition {
      num_newer_versions = 20
    }
    action {
      type = "Delete"
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
