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

# Lets the operator impersonate secret-pruner to run
# backend/scripts/smoke_test_secret_pruner.py — mocked unit tests can't catch
# a wrong IAM grant, wrong OIDC audience, or wrong function packaging, only a
# real invocation authenticated as the real identity can. Same reasoning as
# service_accounts.tf's backend_operator_impersonation for mfs-backend.
resource "google_service_account_iam_member" "pruner_operator_impersonation" {
  service_account_id = google_service_account.secret_pruner.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "user:${var.state_admin_email}"
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
# Weekly, Monday 05:00 UTC — no functional dependency on anything else
# anymore (Instagram publishing, which this schedule used to trail by an
# hour, is deprecated; see terraform.tfvars and docs/DEPLOYMENT.md § MCP
# server § Instagram publishing). Kept at this slot mainly to avoid
# colliding with weekly-usage-report (backend-service/scheduler.tf, Monday
# 13:00 UTC) and budget-breaker-reset (cost-controls/billing.tf, monthly,
# 1st at 08:00 UTC) — otherwise arbitrary.
#
# With Instagram's job gone, this is a straight swap, not a genuine 4th job:
# the billing account still has exactly 3 Cloud Scheduler jobs (this one,
# weekly-usage-report, budget-breaker-reset), all within the free 3-job
# allowance — see docs/DEPLOYMENT.md § Secret version pruning § Cost.
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
# Three separate policies, not conditions on one policy. Cloud Monitoring
# requires a condition_matched_log ("LogMatch") condition to be the *only*
# condition in its policy — confirmed against the API guidance ("If you use
# a LogMatch condition, it must be the only condition in your alerting
# policy") and consistent with the fact that LogMatch is evaluated by
# querying Cloud Logging directly rather than through a Monitoring metric.
# Mixing SECRET_PRUNE_ANOMALY, SECRET_PRUNE_ERROR, and the Scheduler-failure
# threshold in one policy — the original design — would have been rejected
# by `terraform apply`, and only after the function, Scheduler job, and log
# metric had already been created.
resource "google_monitoring_alert_policy" "secret_prune_anomaly" {
  project = var.gcp_project_id

  display_name = "Secret pruner: non-ENABLED latest version"
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

  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
  }

  notification_channels = [var.notification_channel]

  documentation {
    content   = <<-EOT
      A secret's numerically latest version is not ENABLED, so the pruner
      skipped it entirely rather than guessing which older version is really
      current. Investigate: `gcloud secrets versions list <secret-id>`.
      Usually a rotation added a version and never enabled it. Version
      numbers never change, so the fix has to change what counts as
      "latest," not just poke at some other version:
        - If that latest version's value is actually good: enable that exact
          version — `gcloud secrets versions enable <that-version>
          --secret=<secret-id>`.
        - If it's bad and should never be enabled: add a fresh version on top
          of it — `gcloud secrets versions add <secret-id> --data-file=-` —
          so a newer, enabled version becomes the latest. The bad version
          stays disabled and harmless; it's still protected from destruction
          by the same floor that protects any two most-recent enabled
          versions, and ages out of that protection naturally as further
          rotations happen.
      Either way, the pruner resumes normal handling for that secret next run
      once its latest version is ENABLED again.
    EOT
    mime_type = "text/markdown"
  }
}

resource "google_monitoring_alert_policy" "secret_prune_error" {
  project = var.gcp_project_id

  display_name = "Secret pruner: list/destroy failure"
  severity     = "WARNING"
  combiner     = "OR"

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
      A secret couldn't be listed, or a version failed to destroy (e.g. an
      etag conflict from a concurrent change). Check the `secret-pruner`
      Cloud Run revision's logs for the SECRET_PRUNE_ERROR line with the
      secret_id and underlying error. Cloud Scheduler already retries the
      whole run a few times on its own; this firing means either those
      retries also failed, or you're seeing it before they've run.
    EOT
    mime_type = "text/markdown"
  }
}

# condition_matched_log, not a log-based metric + condition_threshold (the
# original design here): a metric-threshold policy backed by a metric that
# only ever emits on failure never emits a healthy/zero point, so its
# incident stays open for the default 7-day auto-close window and a second
# failure inside that window (next week's run, or its own retries) reuses
# the same open incident instead of notifying again — confirmed against
# Cloud Monitoring's own incident-lifecycle docs. Separately, the
# `notification_rate_limit` below was silently inert on the old
# condition_threshold version: confirmed against the Alerting API reference
# for AlertStrategy.notification_rate_limit — "Required for log-based
# alerting policies, i.e. policies with a LogMatch condition. This limit is
# not implemented for alerting policies that do not have a LogMatch
# condition." Matching secret_prune_anomaly/secret_prune_error's shape above
# avoids both problems and drops the log-based metric and its 3-minute
# apply-time propagation wait entirely.
#
# This does NOT cover a job that's silently paused/disabled (zero attempts
# of any kind, so no ERROR log entry is ever written to match either) —
# verified live against the real Monitoring API that every mechanism
# capable of expressing "no execution in over a week" — condition_absent,
# MQL's absent_for, and PromQL's absent_over_time — rejects a window longer
# than ~25 hours for a log-based metric, and this job's cadence is weekly.
# Closing that gap for real would mean a second, more-frequent heartbeat
# job — real new infrastructure and cost for a failure mode only a manual
# `gcloud scheduler jobs pause` or console action can trigger in the first
# place, and that's already visible via `gcloud scheduler jobs describe
# secret-version-pruner`. Not worth a 4th Scheduler job for that.
#
# The filter excludes debugInfo:"UNREACHABLE_5xx" because an application
# failure inside the function (any SECRET_PRUNE_ERROR) also makes Cloud
# Scheduler log its own AttemptFinished severity=ERROR entry for that same
# request — the target *was* reached and ran, it just returned a 500.
# Confirmed live against a real failing execution of this project's
# weekly-usage-report job (also returning 500s in production):
# jsonPayload.debugInfo = "URL_UNREACHABLE-UNREACHABLE_5xx. Original HTTP
# response code number = 500". Cloud Scheduler's troubleshooting docs
# confirm UNREACHABLE_5xx specifically means "the destination target
# returns an HTTP 5xx or 429 error" (reached and ran), as opposed to e.g.
# URL_ERROR-ERROR_AUTHENTICATION (401, genuinely never reached — the real
# OIDC-failure case this policy exists for) or the DNS/connection-reset
# codes. Without the exclusion, secret_prune_error and this policy would
# both fire for the exact same application failure, and this one's name
# and documentation would misdirect the responder toward OIDC/routing.
# Verified live that the exclusion is correctly scoped: re-running the
# same query with `NOT jsonPayload.debugInfo:"UNREACHABLE_5xx"` against
# weekly-usage-report's known-failing history returns zero rows — it drops
# exactly the reached-the-target case and nothing else.
#
# main.py's top-level try/except (see its own comment) guarantees every
# failure path still logs SECRET_PRUNE_ERROR before returning 500, so
# excluding UNREACHABLE_5xx here doesn't create a silent gap for failures
# that happen outside the per-secret loop.
resource "google_monitoring_alert_policy" "secret_pruner_scheduler_failure" {
  project = var.gcp_project_id

  display_name = "Secret pruner: Scheduler execution failed"
  severity     = "WARNING"
  combiner     = "OR"

  conditions {
    display_name = "Scheduler execution failed before reaching the function"

    condition_matched_log {
      filter = <<-EOT
        resource.type="cloud_scheduler_job"
        resource.labels.job_id="${google_cloud_scheduler_job.secret_pruner.name}"
        jsonPayload."@type"="type.googleapis.com/google.cloud.scheduler.logging.AttemptFinished"
        severity="ERROR"
        NOT jsonPayload.debugInfo:"UNREACHABLE_5xx"
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
      The triggered HTTP call itself never reached the function's own code
      (OIDC token minting, IAM, routing, or a cold-start timeout), so
      neither the anomaly nor the error alert ever had a chance to fire —
      this is deliberately narrower than "Cloud Scheduler logged any error
      for this job": an application failure (any SECRET_PRUNE_ERROR) also
      makes Cloud Scheduler log its own ERROR entry for that same request,
      but that case is excluded here and handled by the "list/destroy
      failure" alert instead, since the function did run. Check
      `gcloud logging read 'resource.type="cloud_scheduler_job"
      resource.labels.job_id="secret-version-pruner"'` for the
      AttemptFinished entry's `status` and `debugInfo` fields — a common
      cause is the OIDC/invoker IAM bindings drifting (secret_pruner.tf's
      scheduler_mints_pruner_oidc / secret_pruner_invoker) or the function
      itself failing to deploy.

      This alert does NOT cover a job that is silently paused/disabled
      (zero attempts of any kind, so no ERROR log entry is ever written to
      match either) — see the comment above this resource for why no Cloud
      Monitoring condition can express "no execution in over a week"
      against a weekly-cadence log-based metric. If pruning seems to have
      stopped entirely and neither this alert nor the other two have fired,
      check manually: `gcloud scheduler jobs describe
      secret-version-pruner --location us-central1` (state should be
      ENABLED), or trigger one directly with `gcloud scheduler jobs run
      secret-version-pruner --location us-central1`.
    EOT
    mime_type = "text/markdown"
  }
}
