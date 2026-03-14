# ─── GCS Bucket for Recipe Images ──────────────────────────────────────────────
# Uniform bucket-level access + Public read access for images

resource "google_storage_bucket" "images" {
  project                     = var.gcp_project_id
  name                        = "${var.gcp_project_id}-images"
  location                    = var.gcp_region
  force_destroy               = false
  uniform_bucket_level_access = true

  cors {
    origin          = split(",", var.allowed_origins)
    method          = ["GET", "HEAD", "OPTIONS"]
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
