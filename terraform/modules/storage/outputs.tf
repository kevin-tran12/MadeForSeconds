output "images_bucket_name" {
  description = "Public bucket holding recipe images"
  value       = google_storage_bucket.images.name
}

output "receipts_bucket_name" {
  description = "Private, versioned bucket holding receipts (tax records)"
  value       = google_storage_bucket.receipts.name
}

output "firestore_database_name" {
  description = "Firestore database name — \"(default)\", the only one this project can have"
  value       = google_firestore_database.default.name
}
