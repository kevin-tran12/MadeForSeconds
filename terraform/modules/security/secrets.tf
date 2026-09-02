# ─── Secret Manager ───────────────────────────────────────────────────────────
# Terraform creates the secret container and seeds an initial value from tfvars.
# After the first apply, lifecycle { ignore_changes = [secret_data] } ensures
# subsequent applies never touch the value — rotate secrets out-of-band:
#
#   echo -n "new-value" | gcloud secrets versions add <secret-id> --data-file=-
#
# Cloud Run always reads "latest", so it picks up new versions automatically
# on the next deployment or manual revision update.
#
# version_destroy_ttl (Epic 2, story 2.3): every "destroy" call — whether from
# module.secret-maintenance's automated pruner or a manual
# `gcloud secrets versions destroy` — only disables the version immediately;
# permanent, unrecoverable deletion happens 7 days later. Recovery in that
# window is `gcloud secrets versions enable VERSION --secret=ID`, which is
# deliberately a permission the pruner's own role does not hold (see
# modules/secret-maintenance/secret_pruner.tf) — a bug in the thing that
# destroys versions must not also be able to compromise the thing that undoes
# its mistakes.

resource "google_secret_manager_secret" "admin_emails" {
  project   = var.gcp_project_id
  secret_id = "admin-emails"

  version_destroy_ttl = "604800s" # 7 days

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "admin_emails_initial" {
  secret      = google_secret_manager_secret.admin_emails.id
  secret_data = var.admin_emails

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# MCP auth uses WorkOS OAuth (public-key JWKS validation) — no secret required.

# Redis URL — contains embedded credentials; only created when redis_url is provided
resource "google_secret_manager_secret" "redis_url" {
  count     = var.redis_url != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "redis-url"

  version_destroy_ttl = "604800s" # 7 days — see the comment above admin_emails

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "redis_url_initial" {
  count       = var.redis_url != "" ? 1 : 0
  secret      = google_secret_manager_secret.redis_url[0].id
  secret_data = var.redis_url

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Stripe secret key — only created when stripe_secret_key is provided
resource "google_secret_manager_secret" "stripe_secret_key" {
  count     = var.stripe_secret_key != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "stripe-secret-key"

  version_destroy_ttl = "604800s" # 7 days — see the comment above admin_emails

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "stripe_secret_key_initial" {
  count       = var.stripe_secret_key != "" ? 1 : 0
  secret      = google_secret_manager_secret.stripe_secret_key[0].id
  secret_data = var.stripe_secret_key

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Stripe webhook signing secret
resource "google_secret_manager_secret" "stripe_webhook_secret" {
  count     = var.stripe_webhook_secret != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "stripe-webhook-secret"

  version_destroy_ttl = "604800s" # 7 days — see the comment above admin_emails

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "stripe_webhook_secret_initial" {
  count       = var.stripe_webhook_secret != "" ? 1 : 0
  secret      = google_secret_manager_secret.stripe_webhook_secret[0].id
  secret_data = var.stripe_webhook_secret

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Subscriber JWT signing secret
resource "google_secret_manager_secret" "subscriber_jwt_secret" {
  count     = var.subscriber_jwt_secret != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "subscriber-jwt-secret"

  version_destroy_ttl = "604800s" # 7 days — see the comment above admin_emails

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "subscriber_jwt_secret_initial" {
  count       = var.subscriber_jwt_secret != "" ? 1 : 0
  secret      = google_secret_manager_secret.subscriber_jwt_secret[0].id
  secret_data = var.subscriber_jwt_secret

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Resend API key — for sending cancellation confirmation emails
resource "google_secret_manager_secret" "resend_api_key" {
  count     = var.resend_api_key != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "resend-api-key"

  version_destroy_ttl = "604800s" # 7 days — see the comment above admin_emails

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "resend_api_key_initial" {
  count       = var.resend_api_key != "" ? 1 : 0
  secret      = google_secret_manager_secret.resend_api_key[0].id
  secret_data = var.resend_api_key

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# Instagram access token — seeded once from tfvars, then auto-rotated by the
# backend (Cloud Scheduler → /api/internal/instagram/refresh-token adds new
# versions). ignore_changes keeps Terraform from clobbering rotated values.
resource "google_secret_manager_secret" "instagram_access_token" {
  count     = var.instagram_access_token != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = "instagram-access-token"

  version_destroy_ttl = "604800s" # 7 days — see the comment above admin_emails

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "instagram_access_token_initial" {
  count       = var.instagram_access_token != "" ? 1 : 0
  secret      = google_secret_manager_secret.instagram_access_token[0].id
  secret_data = var.instagram_access_token

  lifecycle {
    ignore_changes = [secret_data]
  }
}

# ─── One list of secrets, not three ───────────────────────────────────────────
#
# Every secret above, keyed by logical name. Optional ones are null when their
# source variable was blank — try() turns the count-0 index-out-of-range into
# null rather than an error.
#
# This map is the single source of truth for the two things that must never
# disagree: the secret_ids this module hands to Cloud Run, and the
# secretAccessor bindings the runtime SA holds. They used to be written out
# separately, and they drifted — cloud_run.tf injected stripe-secret-key,
# stripe-webhook-secret, subscriber-jwt-secret and resend-api-key while
# service_accounts.tf granted access to none of them. Cloud Run rejects a
# revision that references a secret its service identity cannot read, so
# filling in any of those four documented tfvars would have failed the deploy
# outright. Deriving both from one map is what stops that recurring.
locals {
  created_secrets = {
    admin_emails           = google_secret_manager_secret.admin_emails.secret_id
    redis_url              = try(google_secret_manager_secret.redis_url[0].secret_id, null)
    stripe_secret_key      = try(google_secret_manager_secret.stripe_secret_key[0].secret_id, null)
    stripe_webhook_secret  = try(google_secret_manager_secret.stripe_webhook_secret[0].secret_id, null)
    subscriber_jwt_secret  = try(google_secret_manager_secret.subscriber_jwt_secret[0].secret_id, null)
    resend_api_key         = try(google_secret_manager_secret.resend_api_key[0].secret_id, null)
    instagram_access_token = try(google_secret_manager_secret.instagram_access_token[0].secret_id, null)
  }

  # The subset that exists for this deployment — every one of them needs an
  # accessor binding, because every one of them exists to be read by the backend.
  existing_secrets = { for name, secret_id in local.created_secrets : name => secret_id if secret_id != null }
}
