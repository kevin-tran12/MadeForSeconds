variable "gcp_project_id" {
  description = "GCP project ID"
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
  description = "Docker image for the FastAPI backend (e.g., us-central1-docker.pkg.dev/PROJECT/mfs/backend:latest)"
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
  description = "WorkOS AuthKit domain — the OAuth issuer for MCP auth (e.g. https://<slug>.authkit.app)"
  type        = string
  default     = ""
}

variable "mcp_resource_url" {
  description = "Public URL of the MCP resource endpoint (e.g. https://<cloud-run-url>/mcp)"
  type        = string
  default     = ""
}

variable "redis_url" {
  description = "Redis connection URL for shared caching — use Upstash free tier (rediss://default:TOKEN@host.upstash.io:6379)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_secret_key" {
  description = "Stripe secret API key (sk_live_...)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_webhook_secret" {
  description = "Stripe webhook signing secret (whsec_...)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_product_id" {
  description = "(Optional) Legacy Stripe Product ID for donations (prod_...)"
  type        = string
  default     = ""
}

variable "subscriber_jwt_secret" {
  description = "Secret key for signing subscriber JWT tokens (min 32 chars)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "resend_api_key" {
  description = "Resend API key for sending cancellation confirmation emails"
  type        = string
  sensitive   = true
  default     = ""
}

variable "frontend_url" {
  description = "Frontend URL for building links in emails (e.g., https://madeforseconds.pages.dev)"
  type        = string
  default     = "https://madeforseconds.pages.dev"
}

# ─── Instagram (MCP publishing) ─────────────────────────────────────────────

variable "instagram_user_id" {
  description = "Instagram Business/Creator account numeric id (for MCP publishing)"
  type        = string
  default     = ""
}

variable "instagram_access_token" {
  description = "Initial long-lived Instagram access token — seeds the secret; thereafter auto-rotated"
  type        = string
  sensitive   = true
  default     = ""
}

# ─── Cost Protection ────────────────────────────────────────────────────────

variable "billing_account" {
  description = "GCP billing account ID (format: XXXXXX-XXXXXX-XXXXXX)"
  type        = string
}

variable "monthly_budget_amount" {
  description = "Monthly budget cap in USD — alerts and auto-kill trigger at this amount"
  type        = number
  default     = 1
}

variable "alert_email" {
  description = "Email address for budget alert notifications"
  type        = string
}
