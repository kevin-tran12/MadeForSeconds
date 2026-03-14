# ─── Firestore Database ───────────────────────────────────────────────────────
# Always-free tier: 1 GiB storage · 50K reads/day · 20K writes/day · 10 GiB egress/mo

resource "google_firestore_database" "default" {
  project                     = var.gcp_project_id
  name                        = "(default)"
  location_id                 = var.gcp_region
  type                        = "FIRESTORE_NATIVE"
  delete_protection_state     = "DELETE_PROTECTION_ENABLED"

  depends_on = [google_project_service.required_apis]
}
