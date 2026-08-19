terraform {
  # Pinned, not a floor. The CLI version is also recorded in .terraform-version
  # (tfenv/tfswitch) and in the CI workflow — all three must move together, or
  # `fmt -check` starts failing on formatting another version considered clean.
  # State format upgrades are one-way: once a newer CLI writes this state, older
  # CLIs refuse to read it, so every machine has to be on the same version.
  required_version = "~> 1.15"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
    # Used to wait out log-based metric propagation — see logging_alerts.tf.
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
    # Zips the budget-breaker function source in billing.tf. Declared explicitly
    # because it was previously inferred with no constraint at all — and its
    # output_md5 names the deployed object, so a silent version bump here changes
    # what gets deployed.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.8"
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region

  # Use the project ID for quota/billing to avoid Error 403
  user_project_override = true
  billing_project       = var.gcp_project_id
}

provider "google-beta" {
  project = var.gcp_project_id
  region  = var.gcp_region

  user_project_override = true
  billing_project       = var.gcp_project_id
}
