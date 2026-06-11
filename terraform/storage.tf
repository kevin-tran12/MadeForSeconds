# ─── GCS Bucket for Recipe Images ──────────────────────────────────────────────
# Uniform bucket-level access + Public read access for images

resource "google_storage_bucket" "images" {
  project                     = var.gcp_project_id
  name                        = "${var.gcp_project_id}-images"
  location                    = var.gcp_region
  force_destroy               = false
  uniform_bucket_level_access = true

  cors {
    origin = split(",", var.allowed_origins)
    method = ["GET", "HEAD", "OPTIONS"]
    # Best practice: List specific headers needed for delivery and browser caching
    response_header = [
      "Content-Type",
      "Cache-Control",
      "Content-Length",
      "Content-Disposition",
      "ETag",
      "Last-Modified"
    ]
    max_age_seconds = 3600
  }
}

# Grant public read access to all objects in the bucket
resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.images.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# Grant backend service account upload access — scoped to this bucket only
resource "google_storage_bucket_iam_member" "backend_upload" {
  bucket = google_storage_bucket.images.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.backend.email}"
}

# ─── GCS Bucket for Receipts (Private — tax audit data) ─────────────────────
# No public access. Served via time-limited signed URLs only.

resource "google_storage_bucket" "receipts" {
  project                     = var.gcp_project_id
  name                        = "${var.gcp_project_id}-receipts"
  location                    = var.gcp_region
  force_destroy               = false
  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  # Auto-transition to cheaper storage tiers (receipts rarely accessed after upload)
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  # No deletion lifecycle — 7+ year retention for tax records
}

# Backend needs full object access (upload + generate signed URLs)
resource "google_storage_bucket_iam_member" "backend_receipts" {
  bucket = google_storage_bucket.receipts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.backend.email}"
}
