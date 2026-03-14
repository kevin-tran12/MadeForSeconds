# ─── Cloud Run Service ────────────────────────────────────────────────────────
# Always-free tier: 2M req/mo · 360K GB-sec · 180K vCPU-sec · 1 GB egress
# Region MUST be us-central1, us-east1, or us-west1 for free egress.

resource "google_cloud_run_v2_service" "backend" {
  project  = var.gcp_project_id
  name     = "mfs-backend"
  location = var.gcp_region

  deletion_protection = false

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
        name  = "ADMIN_EMAILS"
        value = var.admin_emails
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = var.allowed_origins
      }
      env {
        name  = "GCS_BUCKET_NAME"
        value = google_storage_bucket.images.name
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
    }

    scaling {
      # Scale to zero = free when idle
      min_instance_count = 0
      # Cap at 2 to stay within free egress budget
      max_instance_count = 2
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
