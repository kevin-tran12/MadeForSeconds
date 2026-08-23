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

# Bridges Secret Manager IAM's eventual consistency between module.security's
# accessor bindings and module.backend-service's Cloud Run revision.
#
# module.backend-service only takes module.security.secret_ids as an input —
# an output that depends on the secret *containers*, not the accessor
# bindings that grant read access to them (see secrets.tf and
# service_accounts.tf in modules/security). Referencing that output alone
# creates no ordering guarantee: Terraform is free to apply the Cloud Run
# update and the accessor bindings in parallel once the secret containers
# exist, since neither references the other. On first-time enablement of
# Stripe, subscriber cancellation, or Resend, that meant a Cloud Run revision
# could be created — and validated against Secret Manager IAM — before the
# binding granting it access even finished applying, let alone before
# Google's IAM system had propagated it (Google documents ~2 minutes typical,
# up to 7+ minutes). Cloud Run checks every referenced secret synchronously
# at revision creation, so this was a hard failure, not a degraded one.
#
# Same shape as observability/error_alerts.tf's wait_for_log_metrics:
# depends_on the whole producing module — matching this file's existing
# all-or-nothing dependency idiom (google_project_service.required_apis
# below) rather than hand-picking the specific accessor-binding resources.
#
# time_sleep only sleeps on create, so a bare depends_on protects the very
# first apply and nothing after: docs/DEPLOYMENT.md lists "adding or rotating
# a secret" as an ordinary reason to run apply later, and turning on Stripe,
# subscriber cancellation, or Resend for the first time — this resource's own
# motivating example — is exactly that case. Without a reason to replace it,
# an already-applied time_sleep is a no-op on every later apply, so the new
# accessor binding for a freshly-enabled secret would race the Cloud Run
# update again, unprotected, on whichever apply first grants it.
#
# triggers closes that: it's keyed on the actual set of granted accessors, not
# on which optional tfvars are non-blank, so it tracks what Terraform is about
# to create rather than what the operator typed. Any change to that set
# — a secret added or removed — forces this resource to be replaced, which
# means a fresh 180s sleep ordered before backend-service's update, on
# whichever apply introduces the change. An apply that changes nothing about
# the granted set costs nothing, same as before.
#
# Normalized the same way as terraform/outputs.tf's secrets_missing_accessor:
# a live plan against already-applied state can echo an existing accessor's
# secret_id back fully qualified (projects/P/secrets/NAME) while a
# freshly-created one is still the short form this module configures. Left
# unnormalized, that representation-only difference changes this value and
# replaces the resource — a spurious 180s wait with no accessor actually
# added or removed.
#
# If a from-scratch (or newly-triggered) apply still races the documented
# worst case, re-running apply is safe: Cloud Run's revision creation is
# idempotent, and the previous working revision keeps serving until a new one
# passes its startup probe (docs/DEPLOYMENT.md § Updating the backend).
#
# One-directional: this protects additions (a blank secret being filled in),
# not removals. Depends_on the whole module gives one apply-order guarantee
# in both directions — module.security (including any destroys) fully
# completes before backend-service — which is correct for additions but
# backwards for removing an optional secret: the secret and its accessor
# binding are destroyed, then this resource replaces and re-sleeps 180s,
# and only then does backend-service drop the now-dangling env reference.
# A scale-to-zero cold start landing in that window fails, referencing a
# secret that no longer exists. See docs/DEPLOYMENT.md § Removing an
# optional secret for the safe procedure — this cannot be fixed with a
# smarter trigger, because the trigger only controls how long to wait, and
# the removal case needs the opposite ordering, not a wait.
resource "time_sleep" "wait_for_secret_accessors" {
  depends_on = [module.security]

  create_duration = "180s"

  triggers = {
    accessors = join(",", sort([
      for id in module.security.granted_secret_accessors : regex("[^/]+$", id)
    ]))
  }
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
  deploy_sa_id     = module.security.deploy_sa_id
  secret_ids       = module.security.secret_ids

  # Not in Secret Manager, so it cannot come through secret_ids like the other
  # optional env values do — every secret-backed one is gated on its secret_id
  # being non-null instead of on a separate flag.
  stripe_product_id = var.stripe_product_id

  images_bucket_name   = module.storage.images_bucket_name
  receipts_bucket_name = module.storage.receipts_bucket_name
  staging_bucket_name  = module.storage.staging_bucket_name

  scheduler_agent_email = google_project_service_identity.cloudscheduler.email

  depends_on = [google_project_service.required_apis, time_sleep.wait_for_secret_accessors]
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
  images_bucket_name    = module.storage.images_bucket_name

  depends_on = [google_project_service.required_apis]
}
