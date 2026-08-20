# ─── Terraform remote state ───────────────────────────────────────────────────
# State lives in the versioned GCS bucket below. Local state was a single point
# of failure (laptop loss = state loss) and carries secret material in cleartext.
#
# The bucket had to exist before it could back its own state — chicken-and-egg —
# so this block shipped commented until the one-time `init -migrate-state` ran.
# That migration is done; a fresh clone only needs `terraform init`.
#
# Locking is automatic: the GCS backend takes a lock object at
# <prefix>/<workspace>.tflock for the duration of a write, so a second concurrent
# apply is refused rather than interleaved. Nothing extra to provision — there is
# no DynamoDB-equivalent to configure for GCS. If an apply is killed mid-flight
# the lock can outlive it; `terraform force-unlock <id>` clears it, but only ever
# do that once certain no other apply is actually running.
#
# The backend block cannot use variables — the bucket name is hardcoded. It must
# stay in sync with the `name` on the resource below.

terraform {
  backend "gcs" {
    bucket = "made-for-seconds-tf-state"
    prefix = "terraform/state"
  }
}

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

# Direct object access to the state bucket for the operator running Terraform.
#
# This existed in state but not in config — created by an apply from a machine
# whose .tf edit was never committed — so Terraform proposed destroying it as an
# orphan. Adopting it is the right direction: it is a legitimate grant, and the
# project-level roles that would otherwise cover it are broader than intended.
#
# The address is unchanged from what is already in state, so this produces no
# diff. The email must match the casing recorded there exactly — IAM preserves
# the case it was given, and a difference forces replacement of the binding.
resource "google_storage_bucket_iam_member" "tf_state_admin" {
  bucket = google_storage_bucket.tf_state.name
  role   = "roles/storage.objectAdmin"
  member = "user:${var.state_admin_email}"
}
