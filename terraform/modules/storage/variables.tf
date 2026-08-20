# Variable names match the root module's deliberately. The refactor that created
# these modules had to produce a zero-diff plan, and keeping the names identical
# meant the resource bodies moved unchanged — so any diff that did appear was a
# real mistake rather than a rename.

variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "gcp_region" {
  description = "Region for the buckets and the Firestore database. Firestore's location is immutable once set."
  type        = string
}

variable "allowed_origins" {
  description = "Comma-separated CORS origins allowed to fetch from the images bucket"
  type        = string
}

variable "backend_sa_email" {
  description = "Backend runtime service account. IAM bindings live with the resource they grant on, so the bucket grants are here rather than beside the service account."
  type        = string
}
