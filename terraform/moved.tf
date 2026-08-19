# ─── State address moves ──────────────────────────────────────────────────────
#
# These tell Terraform that resources already in state have new addresses, so a
# module refactor is a rename rather than a destroy-and-recreate. Without them
# this change would delete and rebuild every resource listed here, including
# buckets holding images and receipts.
#
# Delete this file once the move has been applied and the plan is clean.

moved {
  from = google_storage_bucket.images
  to   = module.storage.google_storage_bucket.images
}

moved {
  from = google_storage_bucket_iam_member.public_read
  to   = module.storage.google_storage_bucket_iam_member.public_read
}

moved {
  from = google_storage_bucket_iam_member.backend_upload
  to   = module.storage.google_storage_bucket_iam_member.backend_upload
}

moved {
  from = google_storage_bucket.receipts
  to   = module.storage.google_storage_bucket.receipts
}

moved {
  from = google_storage_bucket_iam_member.backend_receipts
  to   = module.storage.google_storage_bucket_iam_member.backend_receipts
}

moved {
  from = google_firestore_database.default
  to   = module.storage.google_firestore_database.default
}

moved {
  from = google_firestore_backup_schedule.daily
  to   = module.storage.google_firestore_backup_schedule.daily
}

moved {
  from = google_firestore_index.recipes_published_created
  to   = module.storage.google_firestore_index.recipes_published_created
}

moved {
  from = google_firestore_index.recipes_published_categories_created
  to   = module.storage.google_firestore_index.recipes_published_categories_created
}

moved {
  from = google_firestore_index.recipes_slug_published
  to   = module.storage.google_firestore_index.recipes_slug_published
}
