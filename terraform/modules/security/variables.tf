# Names match the root module's — see modules/storage/variables.tf for why.

variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "admin_emails" {
  description = "Comma-separated list of admin email addresses"
  type        = string
}

variable "state_admin_email" {
  description = "Google account granted objectAdmin on the Terraform state bucket — the human who runs apply and operational scripts (e.g. the image-pipeline smoke test)"
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

variable "anthropic_api_key" {
  description = "Anthropic API key for the Sous Chef assistant — the secret is only created when this is non-empty"
  type        = string
  sensitive   = true
  default     = ""
}

# ─── Workload Identity Federation (Epic 8, PR 7) ────────────────────────────

variable "deployment_target" {
  description = "Which GCP project's infrastructure topology this apply targets — \"production\" or \"staging\". Gates the WIF pool/provider/mfs-terraform SA, which are created once, in production, only."
  type        = string
}

variable "github_owner" {
  description = "GitHub username or organization that owns the repo — restricts the Workload Identity Federation trust relationship to this repository specifically."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name — see github_owner."
  type        = string
}

variable "staging_gcp_project_id" {
  description = "The staging GCP project id, if it exists — mfs-terraform (created here, in the production project) is also granted the same roles on this project, so one WIF-backed identity can apply Terraform against both environments without a second WIF pool. Blank skips the cross-project grants (e.g. a from-scratch production-only apply, before staging exists)."
  type        = string
  default     = ""
}
