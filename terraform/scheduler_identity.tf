# ─── Cloud Scheduler service identity ─────────────────────────────────────────
# Shared prerequisite for every scheduler job, regardless of which module owns
# that job. GCP only creates this agent lazily on first job creation, so the
# IAM grants that follow (one per module: backend-service grants it access to
# the backend SA, cost-controls grants it access to the budget-killer SA) would
# fail without provisioning it explicitly first.
#
# Declared once at root rather than inside a module — modules cannot share a
# resource with each other directly, only through root-level wiring, and this
# identity is consumed by two different modules.
resource "google_project_service_identity" "cloudscheduler" {
  provider = google-beta
  project  = var.gcp_project_id
  service  = "cloudscheduler.googleapis.com"
}
