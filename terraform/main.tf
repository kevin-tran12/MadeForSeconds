terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
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
