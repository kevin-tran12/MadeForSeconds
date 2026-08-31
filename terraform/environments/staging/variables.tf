# Mirrors terraform/variables.tf — this directory is its own root module (a
# thin wrapper around module.app = ../.., see main.tf), so it needs its own
# variable declarations to accept a tfvars file; Terraform has no mechanism
# to inherit a child module's variable declarations at the root. Two
# variables from the root are deliberately NOT repeated here:
# monthly_budget_amount and secret_pruner_write_enabled_ids only feed
# module.cost-controls / module.secret-maintenance, both entirely gated off
# for staging (see terraform/modules.tf) — passing them through would be
# accepted but never read by anything live, so main.tf just omits them and
# lets the shared module fall back to its own defaults.

variable "gcp_project_id" {
  description = "GCP project ID — the staging project, distinct from production's"
  type        = string
}

variable "gcp_region" {
  description = "GCP region for Cloud Run and Firestore"
  type        = string
  default     = "us-central1"
}

variable "admin_emails" {
  description = "Comma-separated list of admin email addresses"
  type        = string
}

variable "allowed_origins" {
  description = "Comma-separated list of allowed CORS origins"
  type        = string
}

variable "backend_image" {
  description = "Docker image for the FastAPI backend. Build-once/promote-by-digest (PR 10) means this is the SAME image reference production uses, not a separately built staging image."
  type        = string
}

variable "github_owner" {
  description = "GitHub username or organization that owns the repo"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (without owner prefix)"
  type        = string
}

variable "workos_authkit_domain" {
  description = "WorkOS AuthKit domain for MCP auth"
  type        = string
  default     = ""
}

variable "mcp_resource_url" {
  description = "Public URL of the staging MCP resource endpoint"
  type        = string
  default     = ""
}

variable "redis_url" {
  description = "Redis connection URL for staging's cache — a separate Upstash free-tier database, not production's"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_secret_key" {
  description = "Stripe TEST-mode secret key (sk_test_...) — staging never touches live payments"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_webhook_secret" {
  description = "Stripe TEST-mode webhook signing secret (whsec_...)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_product_id" {
  description = "(Optional) Legacy Stripe Product ID"
  type        = string
  default     = ""
}

variable "subscriber_jwt_secret" {
  description = "Secret key for signing subscriber JWT tokens — a distinct value from production's, not reused across environments"
  type        = string
  sensitive   = true
  default     = ""
}

variable "resend_api_key" {
  description = "Resend API key for cancellation confirmation emails"
  type        = string
  sensitive   = true
  default     = ""
}

variable "frontend_url" {
  description = "Staging Cloudflare Pages URL"
  type        = string
  default     = ""
}

variable "instagram_user_id" {
  description = "Left blank for staging — Instagram publishing is deprecated even in production; no reason to configure it twice"
  type        = string
  default     = ""
}

variable "instagram_access_token" {
  description = "Left blank for staging — see instagram_user_id"
  type        = string
  sensitive   = true
  default     = ""
}

variable "state_admin_email" {
  description = "Google account granted objectAdmin on this environment's Terraform state prefix"
  type        = string
}

variable "billing_account" {
  description = "GCP billing account ID — the SAME account as production (Cloud Scheduler's 3-job and Secret Manager's 6-version free limits are per billing account, already fully spent by production; see the deployment_target comment in terraform/variables.tf)"
  type        = string
}

variable "alert_email" {
  description = "Email address for staging alerts"
  type        = string
}
