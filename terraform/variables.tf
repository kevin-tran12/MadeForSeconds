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

# MCP token binding (backend/app/mcp_auth.py). Both landed with #72 as
# backend settings with safe defaults but were never wired here, so
# production could not set them — and WorkOS access tokens carry no email
# claim by default, which meant every MCP token was rejected once #72
# deployed. Runbook: docs/DEPLOYMENT.md § MCP token binding.
variable "mcp_owner_subject" {
  description = "WorkOS user id (user_…) whose access tokens the MCP server accepts as the site owner — the immutable `sub` claim. Blank falls back to matching the token's email claim against admin_emails, which WorkOS does not emit unless a JWT template adds it"
  type        = string
  default     = ""

  validation {
    condition     = var.mcp_owner_subject == "" || startswith(var.mcp_owner_subject, "user_")
    error_message = "mcp_owner_subject must be a WorkOS user id (user_…) or blank."
  }
}

variable "mcp_enforce_audience" {
  description = "Require every MCP access token's `aud` claim to equal mcp_resource_url. Keep true; false is the documented escape hatch for a WorkOS environment with no matching Resource Indicator, not a default posture"
  type        = bool
  default     = true
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

# ─── Sous Chef assistant: Anthropic Workload Identity Federation ─────────────
#
# Ids, not secrets. Cloud Run's runtime service account (mfs-backend)
# authenticates to the Anthropic API with its Google-signed identity token;
# these tell the backend which federation rule to exchange it under
# (backend/app/services/claude_auth.py, docs/DEPLOYMENT.md § Sous Chef
# assistant). All three blank leaves the assistant off — the endpoint answers
# 503 not_configured — and injects nothing. A partial set is a misconfiguration
# the backend would refuse at startup (a crash-looping revision), so it is
# refused here, at plan time, instead.

variable "anthropic_federation_rule_id" {
  description = "Anthropic federation rule (fdrl_…) matching mfs-backend's identity token. Blank leaves the Sous Chef off; set together with anthropic_organization_id and anthropic_service_account_id"
  type        = string
  default     = ""

  validation {
    condition     = var.anthropic_federation_rule_id == "" || startswith(var.anthropic_federation_rule_id, "fdrl_")
    error_message = "anthropic_federation_rule_id must be an Anthropic federation rule id (fdrl_…) or blank."
  }

  validation {
    condition = (
      (var.anthropic_federation_rule_id != "") == (var.anthropic_organization_id != "")
      && (var.anthropic_federation_rule_id != "") == (var.anthropic_service_account_id != "")
    )
    error_message = "anthropic_federation_rule_id, anthropic_organization_id and anthropic_service_account_id must be set together — all three switch the Sous Chef on, all blank keep it off."
  }
}

variable "anthropic_organization_id" {
  description = "Anthropic organization UUID (Claude Console → Settings → Organization) — the organization the federation rule belongs to"
  type        = string
  default     = ""

  validation {
    condition     = var.anthropic_organization_id == "" || can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.anthropic_organization_id))
    error_message = "anthropic_organization_id must be the organization's UUID or blank."
  }
}

variable "anthropic_service_account_id" {
  description = "Anthropic service account (svac_…) the federation rule targets — the identity the assistant's requests act as and are billed to"
  type        = string
  default     = ""

  validation {
    condition     = var.anthropic_service_account_id == "" || startswith(var.anthropic_service_account_id, "svac_")
    error_message = "anthropic_service_account_id must be an Anthropic service account id (svac_…) or blank."
  }
}

variable "anthropic_workspace_id" {
  description = "Anthropic workspace (wrkspc_…, or the literal default) to scope the minted token to. Only needed when the federation rule is enabled for more than one workspace; blank otherwise"
  type        = string
  default     = ""

  validation {
    condition     = var.anthropic_workspace_id == "" || var.anthropic_workspace_id == "default" || startswith(var.anthropic_workspace_id, "wrkspc_")
    error_message = "anthropic_workspace_id must be a workspace id (wrkspc_…), the literal default, or blank."
  }

  validation {
    condition     = var.anthropic_workspace_id == "" || var.anthropic_federation_rule_id != ""
    error_message = "anthropic_workspace_id is meaningless without anthropic_federation_rule_id — set the rule ids first."
  }
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

variable "staging_gcp_project_id" {
  description = "The staging GCP project id, once it exists — mfs-terraform (created only when deployment_target is \"production\") is granted the same roles on this project too, so one Workload Identity Federation pool/SA can apply Terraform against both environments without a second pool. Blank skips those cross-project grants."
  type        = string
  default     = ""
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
