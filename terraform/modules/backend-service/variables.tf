# Names match the root module's — see modules/storage/variables.tf for why.

variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "gcp_region" {
  description = "Region for Cloud Run and Artifact Registry"
  type        = string
}

variable "environment" {
  description = "Value of the backend's ENVIRONMENT env var"
  type        = string
}

variable "allowed_origins" {
  description = "Comma-separated CORS origins, also injected as ALLOWED_ORIGINS"
  type        = string
}

variable "backend_image" {
  description = "Docker image for the FastAPI backend"
  type        = string
}

variable "ar_keep_count" {
  description = "Number of most-recent tagged Artifact Registry images to retain; older tagged images are deleted"
  type        = number
  default     = 5
}

variable "github_owner" {
  description = "GitHub owner for the Cloud Build trigger's repository connection"
  type        = string
}

variable "github_repo" {
  description = "GitHub repo for the Cloud Build trigger's repository connection"
  type        = string
}

variable "workos_authkit_domain" {
  description = "WorkOS AuthKit domain — the MCP OAuth issuer"
  type        = string
}

variable "mcp_resource_url" {
  description = "Public URL of the MCP resource endpoint. Also the base for the internal Instagram-refresh and weekly-usage-report URLs."
  type        = string
}

variable "frontend_url" {
  description = "Frontend URL for building links in emails"
  type        = string
}

variable "alert_email" {
  description = "Destination for the weekly usage report"
  type        = string
}

variable "instagram_user_id" {
  description = "Instagram Business/Creator account id — non-secret config"
  type        = string
}

variable "instagram_access_token" {
  description = "Gates whether the Instagram token-refresh scheduler job is created"
  type        = string
  sensitive   = true
}

# ─── From module.security ──────────────────────────────────────────────────

variable "backend_sa_email" {
  description = "Backend runtime SA email — Cloud Run's service identity, and the Cloud Build / scheduler grant target"
  type        = string
}

variable "backend_sa_name" {
  description = "Backend SA's fully-qualified resource name — what a scheduler job's service_account_id expects"
  type        = string
}

variable "backend_sa_id" {
  description = "Backend SA's resource id. No longer consumed here — the Cloud Build trigger's service_account field reads deploy_sa_id instead — but still threaded through pending the follow-up PR that finishes the identity cutover; see cloudbuild.tf."
  type        = string
}

variable "deploy_sa_id" {
  description = "Deploy SA's resource id — cloudbuild.tf's Cloud Build trigger runs as this identity, not backend_sa_id, so a compromised build inherits deploy-only permissions rather than the runtime service's Firestore/Secret Manager/receipt-bucket access"
  type        = string
}

# There are deliberately no redis_url / stripe_secret_key / stripe_webhook_secret
# / subscriber_jwt_secret / resend_api_key variables here. They used to be passed
# in purely to gate the dynamic env blocks, which meant this module took the same
# fact twice — once as "was the tfvar set" and once as the secret_id itself — and
# the two could drift. secret_ids carries null for a secret that was not created,
# which is the same condition, so cloud_run.tf gates on that instead. Passing the
# secret values in also marked every expression that touched them sensitive, which
# propagated all the way to the root outputs.

variable "stripe_product_id" {
  description = "Not secret and not in Secret Manager; gates AND supplies the value for the dynamic STRIPE_PRODUCT_ID env block"
  type        = string
}

variable "secret_ids" {
  description = "secret_id of each Secret Manager secret, keyed the same as module.security's output. Optional ones may be null."
  type = object({
    admin_emails           = string
    redis_url              = string
    stripe_secret_key      = string
    stripe_webhook_secret  = string
    subscriber_jwt_secret  = string
    resend_api_key         = string
    instagram_access_token = string
  })
}

# ─── From module.storage ───────────────────────────────────────────────────

variable "images_bucket_name" {
  description = "Public images bucket name — injected as GCS_BUCKET_NAME"
  type        = string
}

variable "receipts_bucket_name" {
  description = "Private receipts bucket name — injected as GCS_RECEIPTS_BUCKET_NAME"
  type        = string
}

variable "staging_bucket_name" {
  description = "Private staging bucket for unsanitized recipe-image uploads — injected as GCS_STAGING_BUCKET_NAME"
  type        = string
}

# ─── Root-level shared prerequisite ────────────────────────────────────────

variable "scheduler_agent_email" {
  description = "Cloud Scheduler's service agent email (google_project_service_identity.cloudscheduler, declared at root — shared with module.cost-controls, which needs the same agent for a different grant)"
  type        = string
}
