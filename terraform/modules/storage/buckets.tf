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

# Grant backend service account read/write access — scoped to this bucket only.
#
# objectCreator alone cannot overwrite or delete an existing object (GCP: "Can
# create new objects... but cannot view, delete, or overwrite objects, even
# ones they created themselves"). Every place the backend already replaces an
# object under that role has therefore been silently failing in production:
#   - sanitize_public_image_blob() downloads an object, strips metadata, and
#     calls upload_from_string on the SAME name — an overwrite.
#   - delete_recipe_image_blob() deletes the previous image when a recipe's
#     image_url changes — delete_gcs_blob() wraps the call in a bare
#     try/except: pass, so this has never surfaced as an error anywhere.
# objectUser is the predefined role covering get/create/update/delete/list on
# objects — narrower custom roles are tracked as Epic 2.2 (least-privilege
# pass), not done here to keep this fix small and reviewable.
resource "google_storage_bucket_iam_member" "backend_upload" {
  bucket = google_storage_bucket.images.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${var.backend_sa_email}"
}

# ─── GCS Bucket for Receipts (Private — tax audit data) ─────────────────────
# No public access. Served via time-limited signed URLs only.

resource "google_storage_bucket" "receipts" {
  project                     = var.gcp_project_id
  name                        = "${var.gcp_project_id}-receipts"
  location                    = var.gcp_region
  force_destroy               = false
  uniform_bucket_level_access = true

  # Explicit, like the staging bucket: UBLA governs how access is granted, not
  # whether allUsers can be granted it. Nothing in here should ever be public,
  # so close that door rather than trusting nobody opens it.
  public_access_prevention = "enforced"

  versioning {
    enabled = true
  }

  # The retention this bucket's comments have always claimed, actually enforced.
  #
  # Versioning alone does not deliver it: it protects against overwrites and
  # accidental deletes, but an application bug or a compromised runtime holding
  # objectAdmin can delete every generation explicitly. A retention policy is
  # enforced by GCS itself — no caller, however privileged, can delete or
  # replace an object before it ages out.
  #
  # Deliberately NOT locked. A locked policy cannot be shortened or removed,
  # ever, and the bucket cannot be deleted until the last object ages out — a
  # seven-year commitment that is the owner's to make, not Terraform's to make
  # silently. docs/DEPLOYMENT.md § Receipt & financial-record recovery documents
  # the one-time lock command for when that call is made. Unlocked still stops
  # every delete the application or its service account could issue; it only
  # leaves a deliberate, manual escape hatch for whoever runs Terraform.
  #
  # This is why admin_delete_recipe_receipt unlinks rather than deletes (see
  # backend/app/routes/admin.py) — with this policy a delete would fail anyway,
  # and failing loudly on a tax record is worse than never trying.
  retention_policy {
    retention_period = 220924800 # 2557 days ≈ 7 years, leap days included
    is_locked        = false
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

  # No deletion lifecycle — the retention policy above is what holds these for
  # seven years, and there is deliberately no rule that removes them after.
}

# Backend needs object access to upload receipts and to generate signed URLs
# (V4 signing is checked against the signer's live IAM at request time, so the
# grant has to cover what the URL will do, not just its creation).
#
# Epic 2.2 (least-privilege pass): was roles/storage.objectAdmin. Its delete
# permission was already inert here — the retention policy above refuses
# deletes regardless of IAM — but objectAdmin also carries list and overwrite,
# neither of which any code path uses today. Narrowed to exactly get (signed-
# URL reads) + create (upload). Deliberately NOT list: list_unlinked_receipts()
# (Epic 7.1) doesn't exist yet, so granting list now would be a permission
# sitting unused ahead of the feature that needs it — add it there, alongside
# that feature's own authz checks, not here. IAM and the retention policy are
# two independent controls; narrowing this one is belt-and-suspenders on top
# of the storage-layer control, not a response to a live gap.
resource "google_project_iam_custom_role" "receipts_uploader" {
  project     = var.gcp_project_id
  role_id     = "mfsReceiptsUploader"
  title       = "MFS Receipts Uploader"
  description = "Minimum permissions for the backend to upload receipts and serve them via signed URLs — see buckets.tf"

  permissions = [
    "storage.objects.get",    # signed-URL reads; also required to generate a V4 signed URL
    "storage.objects.create", # upload
  ]
}

resource "google_storage_bucket_iam_member" "backend_receipts" {
  bucket = google_storage_bucket.receipts.name
  role   = google_project_iam_custom_role.receipts_uploader.id
  member = "serviceAccount:${var.backend_sa_email}"
}

# ─── GCS Bucket for Staged (Unsanitized) Recipe Images ─────────────────────
# Private landing zone for the signed-PUT recipe-image flow. The backend has
# no visibility into bytes uploaded that way until update_recipe attaches the
# URL — this bucket exists so those bytes are never publicly readable before
# sanitize_public_image_blob() has stripped them and promoted the result into
# the public images bucket. Ephemeral by design: no versioning, force_destroy
# unlike images/receipts, and auto-deleted after a couple of days to clean up
# uploads that were never attached to a recipe — a real case for an
# LLM-driven agent that PUTs a file and then never calls update_recipe.
resource "google_storage_bucket" "staging" {
  project                     = var.gcp_project_id
  name                        = "${var.gcp_project_id}-images-staging"
  location                    = var.gcp_region
  force_destroy               = true
  uniform_bucket_level_access = true
  # Explicit, unlike images/receipts: UBLA alone doesn't stop a future
  # accidental allUsers grant. This bucket protects nothing permanent, so
  # there is no reason to leave that door open even in principle.
  public_access_prevention = "enforced"

  lifecycle_rule {
    condition {
      age = 2
    }
    action {
      type = "Delete"
    }
  }
}

# Needs create (for the signed PUT to validate — V4 signed URLs are checked
# against the signer's live IAM grants at request time, not frozen at
# generation time), plus get/delete for the promotion step in
# sanitize_public_image_blob(). objectUser bundles get/create/update/delete/
# list, matching the grant already used on the public images bucket.
resource "google_storage_bucket_iam_member" "backend_staging" {
  bucket = google_storage_bucket.staging.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${var.backend_sa_email}"
}
