# ─── Firestore Database ───────────────────────────────────────────────────────
# Always-free tier: 1 GiB storage · 50K reads/day · 20K writes/day · 10 GiB egress/mo

resource "google_firestore_database" "default" {
  project                 = var.gcp_project_id
  name                    = "(default)"
  location_id             = var.gcp_region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"

  depends_on = [google_project_service.required_apis]
}

# Daily managed backup, 7-day retention. Expenses are tax records — losing
# the database to an accidental wipe must be recoverable. Restore via:
#   gcloud firestore databases restore --source-backup=<backup> --destination-database=<name>
resource "google_firestore_backup_schedule" "daily" {
  project   = var.gcp_project_id
  database  = google_firestore_database.default.name
  retention = "604800s" # 7 days

  daily_recurrence {}
}

# ─── Firestore Composite Indexes ──────────────────────────────────────────────

# Default list query: published == True ORDER BY created_at DESC
resource "google_firestore_index" "recipes_published_created" {
  project    = var.gcp_project_id
  collection = "recipes"
  fields {
    field_path = "published"
    order      = "ASCENDING"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
  query_scope = "COLLECTION"
  depends_on  = [google_firestore_database.default]
}

# Category filter query: published == True AND categories ARRAY_CONTAINS x ORDER BY created_at DESC
resource "google_firestore_index" "recipes_published_categories_created" {
  project    = var.gcp_project_id
  collection = "recipes"
  fields {
    field_path = "published"
    order      = "ASCENDING"
  }
  fields {
    field_path   = "categories"
    array_config = "CONTAINS"
  }
  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
  query_scope = "COLLECTION"
  depends_on  = [google_firestore_database.default]
}

# Single recipe lookup: slug == x AND published == True
resource "google_firestore_index" "recipes_slug_published" {
  project    = var.gcp_project_id
  collection = "recipes"
  fields {
    field_path = "slug"
    order      = "ASCENDING"
  }
  fields {
    field_path = "published"
    order      = "ASCENDING"
  }
  query_scope = "COLLECTION"
  depends_on  = [google_firestore_database.default]
}
