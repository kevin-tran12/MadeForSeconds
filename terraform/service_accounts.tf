# ─── Service Account for Cloud Run ────────────────────────────────────────────

resource "google_service_account" "backend" {
  project      = var.gcp_project_id
  account_id   = "mfs-backend"
  display_name = "MadeForSeconds Backend"

  depends_on = [google_project_service.required_apis]
}

# Grant Firestore access
resource "google_project_iam_member" "backend_firestore" {
  project = var.gcp_project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Grant Cloud Logging access
resource "google_project_iam_member" "backend_logging" {
  project = var.gcp_project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Grant access to read the admin-emails secret — scoped to this secret only, not project-wide
resource "google_secret_manager_secret_iam_member" "backend_secret_access" {
  project   = var.gcp_project_id
  secret_id = google_secret_manager_secret.admin_emails.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}
