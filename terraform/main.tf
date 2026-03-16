terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Remote state: GCS bucket must be created before first use.
  #
  # One-time setup:
  #   gcloud storage buckets create gs://<PROJECT_ID>-tfstate \
  #     --location=us-central1 \
  #     --uniform-bucket-level-access
  #   gcloud storage buckets update gs://<PROJECT_ID>-tfstate --versioning
  #
  # Migrate existing local state:
  #   terraform init -migrate-state
  #
  # Replace <PROJECT_ID> below with your actual GCP project ID.
  backend "gcs" {
    bucket = "<PROJECT_ID>-tfstate"
    prefix = "madeforseconds/state"
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region

  # Use the project ID for quota/billing to avoid Error 403
  user_project_override = true
  billing_project       = var.gcp_project_id
}
