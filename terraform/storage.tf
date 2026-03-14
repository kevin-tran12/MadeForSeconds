# ─── GCS Bucket for Recipe Images ──────────────────────────────────────────────
# Uniform bucket-level access + Public read access for images

resource "google_storage_bucket" "images" {
  project                     = var.gcp_project_id
  name                        = "${var.gcp_project_id}-images"
  location                    = var.gcp_region
  force_destroy               = false
  uniform_bucket_level_access = true

  # Allow public read access to all objects
  # This makes image URLs directly accessible in the browser
  cors {
    origin          = split(",", var.allowed_origins)
    method          = ["GET", "HEAD", "OPTIONS"]
    response_header = ["*"]
    max_age_seconds = 3600
  }
}

# Grant public read access to all objects in the bucket
resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.images.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}
