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

variable "mcp_api_key" {
  description = "Bearer token for MCP endpoint authentication (Claude Projects)"
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key for the recipe parser endpoint"
  type        = string
  sensitive   = true
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
  description = "Frontend URL for building links in emails (e.g., https://madeforseconds.com)"
  type        = string
  default     = "https://madeforseconds.com"
}
