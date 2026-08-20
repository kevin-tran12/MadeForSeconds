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

module "backend-service" {
  source = "./modules/backend-service"

  gcp_project_id  = var.gcp_project_id
  gcp_region      = var.gcp_region
  environment     = var.environment
  allowed_origins = var.allowed_origins
  backend_image   = var.backend_image
  github_owner    = var.github_owner
  github_repo     = var.github_repo

  workos_authkit_domain  = var.workos_authkit_domain
  mcp_resource_url       = var.mcp_resource_url
  frontend_url           = var.frontend_url
  alert_email            = var.alert_email
  instagram_user_id      = var.instagram_user_id
  instagram_access_token = var.instagram_access_token

  backend_sa_email = module.security.backend_sa_email
  backend_sa_name  = module.security.backend_sa_name
  backend_sa_id    = module.security.backend_sa_id
  secret_ids       = module.security.secret_ids

  # Gate the dynamic env blocks in cloud_run.tf. secret_ids carries the value
  # once a secret exists; these carry "does it exist at all".
  redis_url             = var.redis_url
  stripe_secret_key     = var.stripe_secret_key
  stripe_webhook_secret = var.stripe_webhook_secret
  stripe_product_id     = var.stripe_product_id
  subscriber_jwt_secret = var.subscriber_jwt_secret
  resend_api_key        = var.resend_api_key

  images_bucket_name   = module.storage.images_bucket_name
  receipts_bucket_name = module.storage.receipts_bucket_name

  scheduler_agent_email = google_project_service_identity.cloudscheduler.email

  depends_on = [google_project_service.required_apis]
}

module "observability" {
  source = "./modules/observability"

  gcp_project_id       = var.gcp_project_id
  backend_service_uri  = module.backend-service.service_uri
  notification_channel = google_monitoring_notification_channel.budget_email.name

  depends_on = [google_project_service.required_apis]
}

module "cost-controls" {
  source = "./modules/cost-controls"

  gcp_project_id        = var.gcp_project_id
  gcp_region            = var.gcp_region
  billing_account       = var.billing_account
  monthly_budget_amount = var.monthly_budget_amount

  project_number        = data.google_project.project.number
  backend_service_name  = module.backend-service.service_name
  notification_channel  = google_monitoring_notification_channel.budget_email.name
  scheduler_agent_email = google_project_service_identity.cloudscheduler.email

  depends_on = [google_project_service.required_apis]
}
