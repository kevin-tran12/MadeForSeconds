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

# Read access — needed to aggregate request logs into the weekly usage report
resource "google_project_iam_member" "backend_logging_viewer" {
  project = var.gcp_project_id
  role    = "roles/logging.viewer"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

# Grant access to read the admin-emails secret — scoped to this secret only, not project-wide
resource "google_secret_manager_secret_iam_member" "backend_secret_access" {
  project   = var.gcp_project_id
  secret_id = google_secret_manager_secret.admin_emails.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

# Allow Cloud Build (running as mfs-backend SA) to deploy Cloud Run services
# that also run as mfs-backend SA — requires actAs permission on itself
resource "google_service_account_iam_member" "backend_act_as_self" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.backend.email}"
}

# Allow the backend to sign GCS URLs via the IAM signBlob API. Cloud Run
# metadata credentials have no private key, so generate_signed_url must call
# iamcredentials.signBlob as the SA itself.
resource "google_service_account_iam_member" "backend_token_creator" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.backend.email}"
}

# Grant access to read the Redis URL secret (only when redis_url is provided)
resource "google_secret_manager_secret_iam_member" "backend_redis_url_access" {
  count     = var.redis_url != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = google_secret_manager_secret.redis_url[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

# Instagram token: the backend reads the latest version at runtime (accessor)
# and writes refreshed versions during rotation (versionAdder).
resource "google_secret_manager_secret_iam_member" "backend_instagram_token_access" {
  count     = var.instagram_access_token != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = google_secret_manager_secret.instagram_access_token[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_secret_manager_secret_iam_member" "backend_instagram_token_adder" {
  count     = var.instagram_access_token != "" ? 1 : 0
  project   = var.gcp_project_id
  secret_id = google_secret_manager_secret.instagram_access_token[0].secret_id
  role      = "roles/secretmanager.secretVersionAdder"
  member    = "serviceAccount:${google_service_account.backend.email}"
}
