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
#
# COST: this is a real recurring charge — Firestore backup storage has no free
# allowance, and backups are full copies, not incremental. These 14 weekly
# copies add ≈$0.42 per GiB of live database per month on top of the ≈$0.21 the
# 7 daily copies already cost. Bounded at ≈$0.63/mo total because live storage
# stays inside the 1 GiB free tier at this scale. Approved on that basis; the
# arithmetic, the measurement command, and what is deliberately excluded are in
# docs/DEPLOYMENT.md § What the backup schedules cost.
#
# The depth is load-bearing only while a recipe-attached receipt's sole record
# of what it belongs to is the recipe document. Once receipts carry a durable
# association record of their own, re-evaluate this rather than keeping it out
# of habit.
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

# ─── Firestore TTL Policies ───────────────────────────────────────────────────

# Stripe webhook idempotency records (backend/app/routes/subscriptions.py) — one
# doc per event ID, kept only long enough to dedupe a replay. The `ttl` field
# (stamped by the backend, 30 days out) must outlive any window Stripe could
# redeliver or replay the event — see the constant's own comment in
# subscriptions.py for why 30 days is the real ceiling, not the 24h
# idempotency-key minimum. This policy tells Firestore to delete the doc once
# its `ttl` has passed. Without this the collection grows unbounded against
# the 1 GiB free-tier ceiling.
#
# COST: unlike ordinary deletes (20K/day free), every TTL-triggered delete is
# billed at $0.01 per 100K documents with no free quota at all — see
# https://cloud.google.com/firestore/pricing. At this project's webhook
# volume that's a fraction of a cent per year; accepted on that basis, same
# as the weekly backup schedule above. Billing is already enabled on this
# project (see modules/cost-controls/billing.tf), so nothing new to provision.
#
# index_config {} (empty) disables Firestore's automatic single-field index
# on `ttl` — nothing ever queries by it, so the index would just be dead
# storage/write overhead.
resource "google_firestore_field" "processed_events_ttl" {
  project    = var.gcp_project_id
  database   = google_firestore_database.default.name
  collection = "processed_events"
  field      = "ttl"

  ttl_config {}
  index_config {}

  depends_on = [google_firestore_database.default]
}
