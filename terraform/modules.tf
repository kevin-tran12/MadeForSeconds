# ─── Modules ──────────────────────────────────────────────────────────────────
# Instantiated in dependency order. Each module takes what it needs as input
# rather than reaching across the configuration, so the boundaries are real
# rather than cosmetic.

module "storage" {
  source = "./modules/storage"

  gcp_project_id  = var.gcp_project_id
  gcp_region      = var.gcp_region
  allowed_origins = var.allowed_origins

  # Bucket-level IAM lives with the buckets, so the module needs the identity
  # it is granting to.
  backend_sa_email = google_service_account.backend.email

  # Firestore cannot be created before its API is enabled. Declared here rather
  # than inside the module so the module stays free of root-only resources.
  depends_on = [google_project_service.required_apis]
}
