terraform {
  required_version = ">= 1.5"

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
