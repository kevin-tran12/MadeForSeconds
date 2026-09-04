# Staging's own root module. terraform/ (the shared module, `module.app`
# below) has no meaningful backend/provider CONFIGURATION of its own here —
# Terraform only honors a `terraform { backend }` block, and applies a
# root module's own provider blocks, when that directory is the actual root
# being run; terraform/state_backend.tf's backend block and terraform/main.tf's
# provider blocks are inert in this context (confirmed: `terraform init`
# emits a harmless "Backend configuration ignored" warning for that reason —
# see terraform/state_backend.tf's own comment). This file supplies the real
# ones for staging.
#
# required_version / required_providers duplicated from terraform/main.tf
# rather than relied-upon-via-inheritance, so this directory's own
# .terraform.lock.hcl resolves deterministically on its own, matching the
# "exact, not a floor" pinning philosophy already established there.

terraform {
  required_version = "1.15.9"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.8"
    }
  }

  # Same physical bucket as production, different prefix — see
  # terraform/state_backend.tf's own comment on why only one environment's
  # apply may manage the bucket resource itself (production's).
  backend "gcs" {
    bucket = "made-for-seconds-tf-state"
    prefix = "terraform/staging-state"
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region

  user_project_override = true
  billing_project       = var.gcp_project_id
}

provider "google-beta" {
  project = var.gcp_project_id
  region  = var.gcp_region

  user_project_override = true
  billing_project       = var.gcp_project_id
}

module "app" {
  source = "../.."

  gcp_project_id  = var.gcp_project_id
  gcp_region      = var.gcp_region
  admin_emails    = var.admin_emails
  allowed_origins = var.allowed_origins
  backend_image   = var.backend_image
  github_owner    = var.github_owner
  github_repo     = var.github_repo

  workos_authkit_domain  = var.workos_authkit_domain
  mcp_resource_url       = var.mcp_resource_url
  mcp_owner_subject      = var.mcp_owner_subject
  mcp_enforce_audience   = var.mcp_enforce_audience
  redis_url              = var.redis_url
  stripe_secret_key      = var.stripe_secret_key
  stripe_webhook_secret  = var.stripe_webhook_secret
  stripe_product_id      = var.stripe_product_id
  subscriber_jwt_secret  = var.subscriber_jwt_secret
  resend_api_key         = var.resend_api_key
  frontend_url           = var.frontend_url
  instagram_user_id      = var.instagram_user_id
  instagram_access_token = var.instagram_access_token

  anthropic_federation_rule_id = var.anthropic_federation_rule_id
  anthropic_organization_id    = var.anthropic_organization_id
  anthropic_service_account_id = var.anthropic_service_account_id
  anthropic_workspace_id       = var.anthropic_workspace_id

  state_admin_email = var.state_admin_email
  billing_account   = var.billing_account
  alert_email       = var.alert_email

  # Always "production" — see the comment on var.environment in
  # terraform/variables.tf for why this stays fixed regardless of
  # deployment_target: staging exists to exercise real auth, real TOTP
  # enforcement, and real Stripe test-mode webhooks, not the dev bypass.
  environment = "production"

  # The one flag that actually distinguishes this apply — gates every
  # production-only resource declared with `count = var.deployment_target ==
  # "production" ? 1 : 0` off for this apply.
  deployment_target = "staging"
}

output "cloud_run_url" {
  value = module.app.cloud_run_url
}
