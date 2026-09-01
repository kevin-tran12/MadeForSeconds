# ─── Cloud Audit Logs configuration ────────────────────────────────────────────
# Closes the P2 finding that monitoring here was availability-only — uptime and
# error-rate alerts (error_alerts.tf, uptime.tf) say whether the service is up,
# not who touched what. Admin-activity logs (IAM grants, resource creation/
# deletion) are always on and free regardless of this config; what's missing
# without it is ADMIN_READ (who *looked*, not just who *changed*) everywhere,
# and DATA_READ/DATA_WRITE on the two services that actually matter for this
# app's threat model: Secret Manager (Stripe/Redis/JWT/Resend credentials) and
# GCS (the receipts bucket holds 7-year tax records).
#
# Deliberately NOT "allServices" DATA_READ/DATA_WRITE — that would also audit
# every Firestore read/write (the app's normal request path, already covered
# by Cloud Run's own request logs) and would blow through the 50 GiB/mo free
# ingest allowance fast. Scoped to exactly the two services a credential or
# document leak would actually go through.

# ADMIN_READ everywhere: who read an IAM policy, a Secret Manager resource's
# metadata, a bucket's ACL, etc. — free-tier eligible, GCP's own audit logging
# guidance recommends this as a baseline regardless of workload.
resource "google_project_iam_audit_config" "all_services_admin_read" {
  project = var.gcp_project_id
  service = "allServices"

  audit_log_config {
    log_type = "ADMIN_READ"
  }
}

# Secret Manager: DATA_READ catches every secret *value* access (who pulled
# the Stripe key, and when — the question log_redaction.py's own backstop
# exists for on the app-log side, this is the infra-log side of the same
# concern). DATA_WRITE catches version adds/destroys outside the app's own
# secret_pruner_function, which already logs its own actions but isn't the
# only path that can write here (a human with secretmanager.admin, for
# instance).
resource "google_project_iam_audit_config" "secretmanager_data" {
  project = var.gcp_project_id
  service = "secretmanager.googleapis.com"

  audit_log_config {
    log_type = "DATA_READ"
  }
  audit_log_config {
    log_type = "DATA_WRITE"
  }
}

# GCS: DATA_READ on object reads. Scoped by the exclusion below rather than
# by exempted_members here — an exemption stops the entry from being
# *generated* (and therefore audited) at all, where the exclusion filter
# still generates it and only drops it from the sink, which is the right
# tradeoff for "expected but not worth storing" rather than "not worth
# knowing about."
resource "google_project_iam_audit_config" "storage_data_read" {
  project = var.gcp_project_id
  service = "storage.googleapis.com"

  audit_log_config {
    log_type = "DATA_READ"
  }
}

# The public images bucket is fetched anonymously by every recipe-page view —
# by design (see modules/storage/buckets.tf), and at any real traffic volume
# its DATA_READ entries alone would consume the bulk of the 50 GiB/mo free
# log-ingest allowance while adding no security signal (anonymous public
# reads of public images are the expected case, not an anomaly to detect).
# The receipts bucket (private, 7-year retention) and the staging bucket are
# NOT excluded — their DATA_READ traffic is exactly what this audit config
# exists to see.
resource "google_logging_project_exclusion" "images_bucket_data_read" {
  project = var.gcp_project_id
  name    = "images-bucket-data-read"

  filter = "protoPayload.serviceName=\"storage.googleapis.com\" AND protoPayload.resourceName:\"projects/_/buckets/${var.images_bucket_name}/\""

  depends_on = [google_project_iam_audit_config.storage_data_read]
}

# Makes the retention this project has always had (GCP's own default for the
# pre-existing `_Default` log bucket) an explicit, reviewable Terraform
# resource rather than an implicit setting nobody chose — same reasoning as
# 8.1's deployment_target gating: an unmanaged default is a decision nobody
# can see in a diff. 30 days matches GCP's default; not changed here.
resource "google_logging_project_bucket_config" "default" {
  project        = var.gcp_project_id
  location       = "global"
  bucket_id      = "_Default"
  retention_days = 30
}
