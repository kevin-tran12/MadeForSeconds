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

# ─── Environment ─────────────────────────────────────────────────────────────
#
# Two DISTINCT concerns, deliberately kept as two variables rather than
# overloaded onto one:
#
#   var.environment       — the backend app's runtime mode (dev-bypass vs not).
#                            Always "production" for both deployment targets
#                            below, including staging — staging exists to
#                            exercise real auth, real TOTP enforcement, and
#                            real Stripe test-mode webhooks, none of which the
#                            dev bypass would test.
#   var.deployment_target — which GCP project's infrastructure topology this
#                            apply is for. Gates resources that must exist
#                            exactly once across both environments (the shared
#                            Terraform state bucket) or that only make sense
#                            for the always-on production system (Cloud
#                            Scheduler jobs, Firestore backup schedules, the
#                            budget breaker, the secret pruner) — see the
#                            `count` expressions on those resources.
#
# Originally there was deliberately no second environment at all (story 1.2):
# Cloudflare Pages previews already covered the frontend, pointed at
# production — and a second environment needs a second GCP project, since
# Firestore's "(default)" database and google_identity_platform_config are
# both per-project singletons. That reasoning held until the operator asked
# for a real `terraform apply` + E2E gate ahead of every production change —
# reversed for the hardening pass's staging + promotion pipeline (Epic 8).
# The free-tier consequence is real and accepted, not free: Cloud Scheduler's
# 3-job limit and Secret Manager's 6-version limit are per *billing account*,
# not per project, and production already consumes both — staging is
# deliberately lean (backend + Firestore + GCS + Identity Platform only, no
# scheduler jobs, no backups, no breaker, no pruner) to keep the added cost to
# a few dollars a month. See docs/adr/ once story 6.2 records this in full.

variable "environment" {
  description = "Value of the backend's ENVIRONMENT env var. Only \"production\" and \"development\" are meaningful — app/config.py treats is_dev as environment == \"development\" and everything else as production, so a typo would silently ship production behaviour."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["production", "development"], var.environment)
    error_message = "environment must be \"production\" or \"development\"."
  }
}

variable "deployment_target" {
  description = "Which GCP project's infrastructure topology this apply targets — \"production\" or \"staging\". Gates resources that must exist exactly once (the shared Terraform state bucket) or that only belong in the always-on production system (Cloud Scheduler jobs, Firestore backups, the budget breaker, the secret pruner). Distinct from var.environment, which controls the backend app's own runtime mode and stays \"production\" for both targets — see the comment above."
  type        = string
  default     = "production"

  validation {
    condition     = contains(["production", "staging"], var.deployment_target)
    error_message = "deployment_target must be \"production\" or \"staging\"."
  }
}

# ─── Terraform state ────────────────────────────────────────────────────────

variable "state_admin_email" {
  description = "Google account granted objectAdmin on the Terraform state bucket — the human who runs apply. Kept in tfvars rather than inline: this repo is public."
  type        = string
}

# ─── Cost Protection ────────────────────────────────────────────────────────

variable "billing_account" {
  description = "GCP billing account ID (format: XXXXXX-XXXXXX-XXXXXX)"
  type        = string
}

variable "monthly_budget_amount" {
  description = "Monthly budget cap in USD — alerts and auto-kill trigger at this amount"
  type        = number
  default     = 15
}

variable "alert_email" {
  description = "Email address for budget alert notifications"
  type        = string
}

# ─── Secret version pruning (Epic 2, story 2.3) ─────────────────────────────

variable "secret_pruner_write_enabled_ids" {
  description = "secret_id values the automated pruner is allowed to actually destroy old versions on. Empty by default — everything runs dry-run (log-only) until the recovery drill against secret-pruner-canary has succeeded. See docs/DEPLOYMENT.md § Secret version pruning."
  type        = list(string)
  default     = []
}
