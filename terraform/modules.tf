# ─── Modules ──────────────────────────────────────────────────────────────────
# Instantiated in dependency order. Each module takes what it needs as input
# rather than reaching across the configuration, so the boundaries are real
# rather than cosmetic.

module "security" {
  source = "./modules/security"

  gcp_project_id = var.gcp_project_id
  admin_emails   = var.admin_emails

  redis_url              = var.redis_url
  stripe_secret_key      = var.stripe_secret_key
  stripe_webhook_secret  = var.stripe_webhook_secret
  subscriber_jwt_secret  = var.subscriber_jwt_secret
  resend_api_key         = var.resend_api_key
  instagram_access_token = var.instagram_access_token

  depends_on = [google_project_service.required_apis]
}

module "storage" {
  source = "./modules/storage"

  gcp_project_id  = var.gcp_project_id
  gcp_region      = var.gcp_region
  allowed_origins = var.allowed_origins

  # Bucket-level IAM lives with the buckets, so the module needs the identity
  # it is granting to.
  backend_sa_email = module.security.backend_sa_email

  # Firestore cannot be created before its API is enabled. Declared here rather
  # than inside the module so the module stays free of root-only resources.
  depends_on = [google_project_service.required_apis]
}
