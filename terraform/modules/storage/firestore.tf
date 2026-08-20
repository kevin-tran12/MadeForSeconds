# ─── Firestore Database ───────────────────────────────────────────────────────
# Always-free tier: 1 GiB storage · 50K reads/day · 20K writes/day · 10 GiB egress/mo

resource "google_firestore_database" "default" {
  project                 = var.gcp_project_id
  name                    = "(default)"
  location_id             = var.gcp_region
  type                    = "FIRESTORE_NATIVE"
  delete_protection_state = "DELETE_PROTECTION_ENABLED"
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

# Weekly backup at the 14-week maximum, alongside the daily one.
#
# Seven days is the wrong horizon for financial records specifically. A receipt
# object now survives for seven years (see buckets.tf), but the Firestore
# document that says which expense it belongs to, for how much, and on what
# date is what makes it evidence rather than an anonymous scan. A bad write or
# an accidental wipe noticed a fortnight later — which is entirely plausible
# for a page nobody visits daily — would age past the daily backups and
# permanently separate the two.
#
# Daily backups stay for fast recovery of recent mistakes; this is the long
# tail. 14 weeks is the maximum Firestore allows for a backup schedule, and
# daily schedules are separately capped at 7 days, which is why depth needs a
# second schedule rather than a longer retention on the first.
resource "google_firestore_backup_schedule" "weekly" {
  project   = var.gcp_project_id
  database  = google_firestore_database.default.name
  retention = "8467200s" # 14 weeks — the Firestore maximum

  weekly_recurrence {
    day = "SUNDAY"
  }
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
