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

# Grant anonymous READ of individual objects — but not the ability to list them.
#
# This was roles/storage.objectViewer, which also carries storage.objects.list.
# Anyone could walk the whole bucket: `GET /storage/v1/b/<bucket>/o` returned 200
# and enumerated every object, including images belonging to unpublished draft
# recipes that are not linked from anywhere public.
#
# legacyObjectReader is the narrower grant: storage.objects.get without .list.
# The bucket stays genuinely public, which is deliberate — signed URLs would
# expire, so they could not be edge-cached or shared, every page load would need
# the backend to mint one, and crawlers could not fetch them at all, which breaks
# OG previews and the RecipeSchema JSON-LD.
resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.images.name
  role   = "roles/storage.legacyObjectReader"
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
