# ─── Secret Manager version pruning ────────────────────────────────────────
# Epic 2, story 2.3. Every secret in modules/security/secrets.tf keeps every
# version forever — admin-emails alone accumulated 5 enabled versions from a
# single day of testing. Secret Manager bills per active (non-destroyed)
# version above a 6-version free allowance aggregated across the whole billing
# account, not per secret, so an unbounded count on even one secret erodes the
# same shared allowance every other secret draws from.
#
# Isolated identity, mirroring modules/cost-controls/billing.tf's
# budget-killer/budget-resetter pattern exactly: a dedicated SA, a Gen2 Cloud
# Function, invoked by Cloud Scheduler with an OIDC token scoped to that SA.
# secretmanager.versions.destroy must never be reachable from mfs-backend —
# that would reintroduce, for Secret Manager, exactly the anti-pattern Epic 2
# (2.1, 2.2) just removed from Cloud Build and Cloud Storage: a public-facing
# runtime identity holding a destructive permission it never legitimately
# uses at request time.

# ─── Canary secret ──────────────────────────────────────────────────────────
# Exists solely to validate the pruner end-to-end — including the recovery
# path — without ever risking a real application secret. See docs/DEPLOYMENT.md
# § Secret version pruning for the drill: add a couple of extra versions via
# `gcloud secrets versions add` (the same out-of-band rotation every other
# secret already uses), add this secret_id to write_enabled_secret_ids, run the
# function, confirm the oldest version moved to DISABLED with a
# scheduled_destroy_time, then `gcloud secrets versions enable` it back and
# confirm the value is still readable. Only after that succeeds should a real
# secret ever be added to the allowlist.
resource "google_secret_manager_secret" "canary" {
  project   = var.gcp_project_id
  secret_id = "secret-pruner-canary"

  version_destroy_ttl = "604800s" # 7 days — see secret_ids' versions in modules/security/secrets.tf for why this matters

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "canary_initial" {
  secret      = google_secret_manager_secret.canary.id
  secret_data = "canary-seed-value"
}

# ─── Pruner identity ─────────────────────────────────────────────────────────

resource "google_service_account" "secret_pruner" {
  project      = var.gcp_project_id
  account_id   = "secret-pruner"
  display_name = "MFS Secret Version Pruner"
}

# Narrower than the predefined roles/secretmanager.secretVersionManager, which
# also grants .add/.disable/.enable and secrets.rotate — none of which pruning
# needs. Deliberately excludes .enable: that is the operator's own recovery
# path (see canary comment above), and a bug in this role's own holder must
# not be able to compromise the thing that undoes its mistakes.
resource "google_project_iam_custom_role" "secret_pruner" {
  project     = var.gcp_project_id
  role_id     = "mfsSecretPruner"
  title       = "MFS Secret Version Pruner"
  description = "Minimum permissions to list and destroy old Secret Manager versions — see secret_pruner.tf"

  permissions = [
    "secretmanager.versions.list",
    "secretmanager.versions.destroy",
  ]
}

# One list, reused for both the per-secret IAM bindings below and the
# function's own SECRET_IDS input — same one-source-of-truth reasoning as
# local.created_secrets in modules/security/secrets.tf. Includes the canary
# alongside every non-null application secret, so the pruner is naturally
# scoped away from the two unrelated Cloud Build OAuth secrets, which never
# appear in var.secret_ids.
locals {
  prunable_secret_ids = merge(
    { for name, id in var.secret_ids : name => id if id != null },
    { canary = google_secret_manager_secret.canary.secret_id }
  )
}

resource "google_secret_manager_secret_iam_member" "pruner_access" {
  for_each = local.prunable_secret_ids

  project   = var.gcp_project_id
  secret_id = each.value
  role      = google_project_iam_custom_role.secret_pruner.id
  member    = "serviceAccount:${google_service_account.secret_pruner.email}"
}

# ─── Cloud Function (Gen 2) ─────────────────────────────────────────────────
# Explicit `source` blocks, not `source_dir` — see billing.tf's identical
# comment: source_dir would pick up local pytest artifacts (__pycache__,
# .pytest_cache) and force a spurious redeploy. output_file_mode keeps the
# archive byte-identical across machines despite Windows having no Unix mode
# bits to report.
data "archive_file" "secret_pruner_source" {
  type        = "zip"
  output_path = "${path.module}/.tmp/secret_pruner_function.zip"

  source {
    content  = file("${path.module}/secret_pruner_function/main.py")
    filename = "main.py"
  }
  source {
    content  = file("${path.module}/secret_pruner_function/requirements.txt")
    filename = "requirements.txt"
  }

  output_file_mode = "0644"
}

resource "google_storage_bucket" "function_source" {
  project                     = var.gcp_project_id
  name                        = "${var.gcp_project_id}-secret-pruner-source"
  location                    = var.gcp_region
  uniform_bucket_level_access = true
  force_destroy               = true
}

resource "google_storage_bucket_object" "secret_pruner_source" {
  name   = "secret_pruner_function-${data.archive_file.secret_pruner_source.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.secret_pruner_source.output_path
}

resource "google_cloudfunctions2_function" "secret_pruner" {
  project  = var.gcp_project_id
  name     = "secret-pruner"
  location = var.gcp_region

  build_config {
    runtime     = "python312"
    entry_point = "prune_secret_versions"

    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.secret_pruner_source.name
      }
    }
  }

  service_config {
    max_instance_count = 1
    available_memory   = "256Mi"
    timeout_seconds    = 120 # one run touches up to 7 secrets, each a separate list + N destroy calls

    service_account_email = google_service_account.secret_pruner.email

    # Scheduler authenticates with an OIDC token; no unauthenticated access.
    ingress_settings = "ALLOW_ALL"

    environment_variables = {
      GCP_PROJECT_ID = var.gcp_project_id
      # Sorted so a Terraform plan never shows a diff from map-ordering churn
      # alone — var.secret_ids and the canary id are stable, but for_each maps
      # and locals.merge() give no ordering guarantee.
      SECRET_IDS               = join(",", sort(values(local.prunable_secret_ids)))
      WRITE_ENABLED_SECRET_IDS = join(",", sort(var.write_enabled_secret_ids))
    }
  }
}

# The scheduler job presents an OIDC token as secret_pruner, so that SA must be
# able to invoke its own function's backing Cloud Run service.
resource "google_cloud_run_v2_service_iam_member" "secret_pruner_invoker" {
  project  = var.gcp_project_id
  location = var.gcp_region
  name     = "secret-pruner"
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.secret_pruner.email}"

  depends_on = [google_cloudfunctions2_function.secret_pruner]
}

# Cloud Scheduler's service agent must be able to mint OIDC tokens as
# secret_pruner. The equivalent grants in backend-service/scheduler.tf and
# cost-controls/billing.tf cover different SAs, so this is a separate binding.
resource "google_service_account_iam_member" "scheduler_mints_pruner_oidc" {
  service_account_id = google_service_account.secret_pruner.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${var.scheduler_agent_email}"
}

# ─── Scheduler ───────────────────────────────────────────────────────────────
# Weekly, the day the Instagram token rotates (backend-service/scheduler.tf,
# 04:00 UTC Monday) but an hour later — so a version that rotation just added
# is already reflected in what "the newest 2" means for that secret, rather
# than being pruned against a stale picture from a week ago.
#
# A genuine 4th Cloud Scheduler job (docs/OPS_BACKLOG.md's free-tier ceilings
# already account for this: the first 3 jobs per billing account are free,
# this one is not, at roughly $0.10/month).
resource "google_cloud_scheduler_job" "secret_pruner" {
  project     = var.gcp_project_id
  region      = var.gcp_region
  name        = "secret-version-pruner"
  description = "Weekly cleanup of old Secret Manager versions past the free-tier allowance"
  schedule    = "0 5 * * 1" # 05:00 UTC every Monday
  time_zone   = "Etc/UTC"

  retry_config {
    retry_count = 3
  }

  http_target {
    http_method = "POST"
    uri         = google_cloudfunctions2_function.secret_pruner.service_config[0].uri

    oidc_token {
      service_account_email = google_service_account.secret_pruner.email
      audience              = google_cloudfunctions2_function.secret_pruner.service_config[0].uri
    }
  }

  depends_on = [
    google_cloud_run_v2_service_iam_member.secret_pruner_invoker,
    google_service_account_iam_member.scheduler_mints_pruner_oidc,
  ]
}

# ─── Alerts ──────────────────────────────────────────────────────────────────
# Two independent conditions on one policy (combiner = OR), matching the two
# log markers secret_pruner_function/main.py emits:
#
#   SECRET_PRUNE_ANOMALY — a secret's numerically latest version is not
#   ENABLED. The pruner deliberately skips destroying anything for that secret
#   rather than guessing which older version is "really" current.
#
#   SECRET_PRUNE_ERROR — a secret couldn't be listed, or one of its versions
#   failed to destroy. This also makes the function return non-2xx, so Cloud
#   Scheduler's retry_config (above) gets a chance to recover on its own —
#   this alert is for when it doesn't, or to make the failure visible
#   immediately rather than waiting on retries to exhaust.
#
# Either way, silence from this alert does not mean nothing needed attention —
# it means nothing was skipped or failed.
resource "google_monitoring_alert_policy" "secret_prune_anomaly" {
  project = var.gcp_project_id

  display_name = "Secret pruner needs attention"
  severity     = "WARNING"
  combiner     = "OR"

  conditions {
    display_name = "Pruner skipped a secret with a non-ENABLED latest version"

    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_run_revision"
        resource.labels.service_name="${google_cloudfunctions2_function.secret_pruner.name}"
        textPayload:"SECRET_PRUNE_ANOMALY"
      EOT
    }
  }

  conditions {
    display_name = "Pruner failed to list or destroy a secret's versions"

    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_run_revision"
        resource.labels.service_name="${google_cloudfunctions2_function.secret_pruner.name}"
        textPayload:"SECRET_PRUNE_ERROR"
      EOT
    }
  }

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
  }

  notification_channels = [var.notification_channel]

  documentation {
    content   = <<-EOT
      secret-pruner hit one of two conditions:

      **Anomaly** — a secret's numerically latest version is not ENABLED, so
      the pruner skipped it entirely rather than guessing which older version
      is really current. Investigate: `gcloud secrets versions list
      <secret-id>`. Usually a rotation added a version and never enabled it —
      decide whether to enable the intended one or disable the stray one,
      then the pruner resumes normal handling for that secret next run.

      **Error** — a secret couldn't be listed, or a version failed to
      destroy (e.g. an etag conflict from a concurrent change). Check the
      `secret-pruner` Cloud Run revision's logs for the SECRET_PRUNE_ERROR
      line with the secret_id and underlying error. Cloud Scheduler already
      retries the whole run a few times on its own; this firing means either
      those retries also failed, or you're seeing it before they've run.
    EOT
    mime_type = "text/markdown"
  }
}
