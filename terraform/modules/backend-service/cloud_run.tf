# ─── Cloud Run Service ────────────────────────────────────────────────────────
# Always-free tier: 2M req/mo · 360K GB-sec · 180K vCPU-sec · 1 GB egress
# Region MUST be us-central1, us-east1, or us-west1 for free egress.

# Optional secret-backed env vars: env var name → the secret it reads from.
#
# Gated on the secret_id being non-null rather than on a separate "was this
# tfvar set" input. module.security creates each optional secret under the same
# count, so a null secret_id means the secret does not exist — the two can never
# disagree, and the five sensitive gating variables this module used to take
# just to re-derive the same fact are gone.
#
# Not incidental: gating on those variables made this whole expression inherit
# their sensitive marking, which propagates to referenced_secret_ids and made
# the root outputs below refuse to render. Secret *ids* are not secret; only
# their values are.
#
# A list rather than a map so the declaration order below is the order the env
# blocks are rendered in — a map would iterate lexicographically and reshuffle
# the container's env list for no reason.
#
# This drives both the dynamic env block and the referenced_secret_ids output,
# so "what Cloud Run injects" is stated exactly once. The IAM bindings that make
# these readable are derived from the same set of secrets in module.security,
# and terraform/tests/secret_access.tftest.hcl asserts the two agree.
locals {
  optional_secret_env = [
    for entry in [
      { name = "REDIS_URL", secret_id = var.secret_ids.redis_url },
      { name = "STRIPE_SECRET_KEY", secret_id = var.secret_ids.stripe_secret_key },
      { name = "STRIPE_WEBHOOK_SECRET", secret_id = var.secret_ids.stripe_webhook_secret },
      { name = "SUBSCRIBER_JWT_SECRET", secret_id = var.secret_ids.subscriber_jwt_secret },
      { name = "RESEND_API_KEY", secret_id = var.secret_ids.resend_api_key },
    ] : entry if entry.secret_id != null
  ]
}

resource "google_cloud_run_v2_service" "backend" {
  project  = var.gcp_project_id
  name     = "mfs-backend"
  location = var.gcp_region

  deletion_protection = true

  lifecycle {
    # The running image is owned by the deploy pipeline — `gcloud run services
    # update` or Cloud Build (docs/DEPLOYMENT.md § Updating the backend) — not
    # by Terraform. var.backend_image only seeds the service on first create.
    #
    # Without this, every terraform apply re-pins the service to whatever
    # var.backend_image (:latest) resolves to right now. A budget-only apply
    # once rolled the backend onto a newer image whose required env vars had
    # not been applied yet, and the apply failed on the crash-looping revision.
    # Image rollout and infra rollout must be able to happen independently.
    #
    # client/client_version are metadata gcloud stamps on deploys it performs.
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  template {
    service_account = var.backend_sa_email
    timeout         = "120s"

    containers {
      image = var.backend_image

      ports {
        container_port = 8000
      }

      env {
        name  = "GCP_PROJECT_ID"
        value = var.gcp_project_id
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = var.allowed_origins
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = var.images_bucket_name
      }
      env {
        name  = "GCS_RECEIPTS_BUCKET_NAME"
        value = var.receipts_bucket_name
      }
      env {
        name  = "GCS_STAGING_BUCKET_NAME"
        value = var.staging_bucket_name
      }

      # ADMIN_EMAILS read from Secret Manager — not passed as plaintext
      env {
        name = "ADMIN_EMAILS"
        value_source {
          secret_key_ref {
            secret  = var.secret_ids.admin_emails
            version = "latest"
          }
        }
      }

      # MCP OAuth — WorkOS AuthKit is the authorization server; the MCP server
      # only validates tokens (public-key JWKS), so no secret is needed here.
      env {
        name  = "WORKOS_AUTHKIT_DOMAIN"
        value = var.workos_authkit_domain
      }

      env {
        name  = "MCP_RESOURCE_URL"
        value = var.mcp_resource_url
      }

      # Secret-backed optional env vars — each read from Secret Manager, each
      # injected only when its tfvar was supplied. See local.optional_secret_env
      # at the top of this file for the list and why it is a list.
      dynamic "env" {
        for_each = local.optional_secret_env
        content {
          name = env.value.name
          value_source {
            secret_key_ref {
              secret  = env.value.secret_id
              version = "latest"
            }
          }
        }
      }

      # STRIPE_PRODUCT_ID — not sensitive, plain value
      dynamic "env" {
        for_each = var.stripe_product_id != "" ? [1] : []
        content {
          name  = "STRIPE_PRODUCT_ID"
          value = var.stripe_product_id
        }
      }

      # FRONTEND_URL — for building links in emails
      env {
        name  = "FRONTEND_URL"
        value = var.frontend_url
      }

      # ALERT_EMAIL — destination for the weekly usage report (same address as
      # the budget/uptime/error alerts configured in terraform/billing.tf and
      # terraform/logging_alerts.tf)
      env {
        name  = "ALERT_EMAIL"
        value = var.alert_email
      }

      # USAGE_REPORT_AUDIENCE — expected OIDC audience for the weekly usage
      # report endpoint, checked in backend/app/routes/internal.py
      env {
        name  = "USAGE_REPORT_AUDIENCE"
        value = local.usage_report_url
      }

      # Instagram (MCP publishing). The access token is NOT injected here — it is
      # read from Secret Manager at runtime so auto-rotated versions are picked up
      # without redeploying. These are non-secret config values.
      env {
        name  = "INSTAGRAM_USER_ID"
        value = var.instagram_user_id
      }
      env {
        name  = "INSTAGRAM_REFRESH_INVOKER_EMAIL"
        value = var.backend_sa_email
      }
      env {
        name  = "INSTAGRAM_REFRESH_AUDIENCE"
        value = local.instagram_refresh_url
      }

      resources {
        limits = {
          # 512Mi: Better buffer for FastAPI + image processing, still well within free tier
          cpu    = "1000m"
          memory = "512Mi"
        }
        # Faster cold starts with no extra cost for scale-to-zero workloads
        startup_cpu_boost = true
        # CPU is throttled when not processing a request (free-tier eligible mode)
        cpu_idle = true
      }

      startup_probe {
        http_get {
          path = "/api/health"
        }
      }

      liveness_probe {
        http_get {
          path = "/api/health"
        }
        period_seconds    = 30
        failure_threshold = 3
      }
    }

    scaling {
      # Scale to zero = free when idle
      min_instance_count = 0
      # Cap at 1 to stay within free tier budget
      max_instance_count = 1
    }
  }
}

# Allow unauthenticated access (public API).
#
# This binding is also the budget breaker's kill switch: tripping removes
# allUsers here, which is what stops requests (and therefore spend). Terraform
# still declares it, so a `terraform apply` while the breaker is tripped will
# re-add it and put the site back online. That is the same drift caveat that
# applies to the scaling config, and the breaker-tripped alert is the mitigation
# — if you get that alert, find out why before applying.
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
