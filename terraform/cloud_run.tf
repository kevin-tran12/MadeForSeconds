# ─── Cloud Run Service ────────────────────────────────────────────────────────
# Always-free tier: 2M req/mo · 360K GB-sec · 180K vCPU-sec · 1 GB egress
# Region MUST be us-central1, us-east1, or us-west1 for free egress.

resource "google_cloud_run_v2_service" "backend" {
  project  = var.gcp_project_id
  name     = "mfs-backend"
  location = var.gcp_region

  deletion_protection = true

  depends_on = [google_project_service.required_apis]

  template {
    service_account = google_service_account.backend.email

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
        value = "production"
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = var.allowed_origins
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = google_storage_bucket.images.name
      }
      env {
        name  = "GCS_RECEIPTS_BUCKET_NAME"
        value = google_storage_bucket.receipts.name
      }

      # ADMIN_EMAILS read from Secret Manager — not passed as plaintext
      env {
        name = "ADMIN_EMAILS"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.admin_emails.secret_id
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

      # REDIS_URL — read from Secret Manager; only injected when redis_url is provided
      dynamic "env" {
        for_each = var.redis_url != "" ? [1] : []
        content {
          name = "REDIS_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.redis_url[0].secret_id
              version = "latest"
            }
          }
        }
      }

      # STRIPE_SECRET_KEY — only injected when provided
      dynamic "env" {
        for_each = var.stripe_secret_key != "" ? [1] : []
        content {
          name = "STRIPE_SECRET_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.stripe_secret_key[0].secret_id
              version = "latest"
            }
          }
        }
      }

      # STRIPE_WEBHOOK_SECRET — only injected when provided
      dynamic "env" {
        for_each = var.stripe_webhook_secret != "" ? [1] : []
        content {
          name = "STRIPE_WEBHOOK_SECRET"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.stripe_webhook_secret[0].secret_id
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

      # SUBSCRIBER_JWT_SECRET — only injected when provided
      dynamic "env" {
        for_each = var.subscriber_jwt_secret != "" ? [1] : []
        content {
          name = "SUBSCRIBER_JWT_SECRET"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.subscriber_jwt_secret[0].secret_id
              version = "latest"
            }
          }
        }
      }

      # RESEND_API_KEY — only injected when provided
      dynamic "env" {
        for_each = var.resend_api_key != "" ? [1] : []
        content {
          name = "RESEND_API_KEY"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.resend_api_key[0].secret_id
              version = "latest"
            }
          }
        }
      }

      # FRONTEND_URL — for building links in emails
      env {
        name  = "FRONTEND_URL"
        value = var.frontend_url
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

# Allow unauthenticated access (public API)
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = google_cloud_run_v2_service.backend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
