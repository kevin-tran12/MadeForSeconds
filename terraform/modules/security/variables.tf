# Names match the root module's — see modules/storage/variables.tf for why.

variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "admin_emails" {
  description = "Comma-separated list of admin email addresses"
  type        = string
}

variable "redis_url" {
  description = "Redis connection URL — the secret is only created when this is non-empty"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_secret_key" {
  description = "Stripe secret API key — the secret is only created when this is non-empty"
  type        = string
  sensitive   = true
  default     = ""
}

variable "stripe_webhook_secret" {
  description = "Stripe webhook signing secret — the secret is only created when this is non-empty"
  type        = string
  sensitive   = true
  default     = ""
}

variable "subscriber_jwt_secret" {
  description = "Secret key for signing subscriber JWT tokens — the secret is only created when this is non-empty"
  type        = string
  sensitive   = true
  default     = ""
}

variable "resend_api_key" {
  description = "Resend API key — the secret is only created when this is non-empty"
  type        = string
  sensitive   = true
  default     = ""
}

variable "instagram_access_token" {
  description = "Initial Instagram access token — the secret is only created when this is non-empty"
  type        = string
  sensitive   = true
  default     = ""
}
