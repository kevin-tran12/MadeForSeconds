# ─── Security detection alerts ─────────────────────────────────────────────────
# Consumes the audit logs audit_log.tf enables. Same log-metric + alert-policy
# pattern as error_alerts.tf, but tuned differently: these events are rare and
# individually consequential (an IAM grant, an unexpected secret access, a
# private bucket's ACL changing), not high-frequency transient blips — so
# every alert here fires on the FIRST occurrence (threshold_value = 0) rather
# than the loose ">5 in 15 min" used for app errors. Alerting on the first
# occurrence of something that should be rare is the right tradeoff; waiting
# for a burst would mean a single real incident goes unnoticed until it
# repeats.
#
# Security Command Center is not available here (see plan/README) — this is
# the substitute: log-based detection rather than SCC's built-in findings.

# ─── IAM policy changes ────────────────────────────────────────────────────────
# Every SetIamPolicy call, any GCP service — project-level role grants,
# bucket/secret/service-account IAM bindings. Deliberately broader than "just
# project-level" — a bucket or secret's own IAM policy can grant access just
# as consequentially as a project role can, and admin-activity logs (which
# this reads) are always on regardless of audit_log.tf's config, so this
# needs no ADMIN_WRITE audit config of its own.

resource "google_logging_metric" "iam_policy_changes" {
  project     = var.gcp_project_id
  name        = "iam_policy_changes"
  description = "Count of SetIamPolicy calls across any service"

  filter = <<-EOT
    protoPayload.methodName:"SetIamPolicy"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# ─── Unusual secret access ─────────────────────────────────────────────────────
# DATA_READ (AccessSecretVersion) and DATA_WRITE (AddSecretVersion,
# DestroySecretVersion) on Secret Manager, excluding the identities that
# access secrets as part of normal operation: mfs-backend (reads its
# injected secrets at Cloud Run cold start), mfs-terraform (reads secret
# values during every plan/apply's refresh — PR 8's own finding, see
# workload_identity.tf), and secret-pruner (prunes old versions). Anything
# left over — a different principal, a human operator, a compromised
# credential — is by construction not routine, so this alerts on the first
# match rather than needing a frequency threshold to separate signal from
# noise.

resource "google_logging_metric" "unusual_secret_access" {
  project     = var.gcp_project_id
  name        = "unusual_secret_access"
  description = "Count of Secret Manager access/mutation by a principal other than the known service accounts"

  filter = <<-EOT
    protoPayload.serviceName="secretmanager.googleapis.com"
    (protoPayload.methodName:"AccessSecretVersion" OR protoPayload.methodName:"AddSecretVersion" OR protoPayload.methodName:"DestroySecretVersion")
    NOT protoPayload.authenticationInfo.principalEmail="mfs-backend@${var.gcp_project_id}.iam.gserviceaccount.com"
    NOT protoPayload.authenticationInfo.principalEmail="mfs-terraform@${var.gcp_project_id}.iam.gserviceaccount.com"
    NOT protoPayload.authenticationInfo.principalEmail="secret-pruner@${var.gcp_project_id}.iam.gserviceaccount.com"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# ─── Private-bucket config changes ─────────────────────────────────────────────
# Scoped to the receipts bucket specifically (7-year tax retention, must
# never be public) rather than all three buckets — the public images bucket
# is *supposed* to have a public-read binding, and Terraform itself
# reconciles it on every apply, so alerting there would just be noise on
# routine applies. A config change (ACL, uniform bucket-level access,
# public-access-prevention) on the one bucket that must always stay private
# is the actual anomaly worth paging on. IAM-policy changes on this bucket
# are also caught by iam_policy_changes above; this additionally catches
# bucket-level metadata updates (storage.buckets.update), which aren't
# SetIamPolicy calls.

resource "google_logging_metric" "receipts_bucket_config_changed" {
  project     = var.gcp_project_id
  name        = "receipts_bucket_config_changed"
  description = "Count of storage.buckets.update calls against the receipts bucket"

  filter = <<-EOT
    protoPayload.serviceName="storage.googleapis.com"
    protoPayload.methodName="storage.buckets.update"
    resource.labels.bucket_name="${var.receipts_bucket_name}"
  EOT

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# Same eventual-consistency wait as error_alerts.tf's own time_sleep — see
# that file's comment for why creating a metric and referencing it from an
# alert policy in the same apply needs this.
resource "time_sleep" "wait_for_detection_metrics" {
  depends_on = [
    google_logging_metric.iam_policy_changes,
    google_logging_metric.unusual_secret_access,
    google_logging_metric.receipts_bucket_config_changed,
  ]

  create_duration = "180s"
}

# This one alerts on the log entries directly rather than on the metric
# above, because a condition_threshold filter must pin resource.type and this
# alert is deliberately "any GCP service". SetIamPolicy entries arrive under
# whichever monitored resource the target belongs to — 60 days of production
# logs show audited_resource, service_account, project and cloud_run_revision,
# and a service nobody has touched yet would add another. Enumerating them
# with one_of() would work today and silently stop covering the next one,
# which is the wrong failure mode for the broadest security alert here. A
# log-match condition has no resource.type dimension at all, so it cannot
# develop that blind spot. The metric above is kept: it still records a
# chartable count of the same filter, it just is not what fires this alert.
resource "google_monitoring_alert_policy" "iam_policy_changes" {
  project      = var.gcp_project_id
  display_name = "MFS IAM policy changed"
  combiner     = "OR"

  conditions {
    display_name = "SetIamPolicy call"

    condition_matched_log {
      filter = "protoPayload.methodName:\"SetIamPolicy\""
    }
  }

  # Required for a log-match condition: without it every matching entry pages.
  alert_strategy {
    notification_rate_limit {
      period = "300s"
    }
  }

  notification_channels = [var.notification_channel]
}

resource "google_monitoring_alert_policy" "unusual_secret_access" {
  project      = var.gcp_project_id
  display_name = "MFS unusual Secret Manager access"
  combiner     = "OR"

  depends_on = [time_sleep.wait_for_detection_metrics]

  conditions {
    display_name = "Secret access by an unexpected principal"

    condition_threshold {
      # audited_resource is right here: every Secret Manager audit entry in 60
      # days of production logs (75 of 75) carries that monitored resource.
      filter          = "resource.type = \"audited_resource\" AND metric.type = \"logging.googleapis.com/user/${google_logging_metric.unusual_secret_access.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_COUNT"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [var.notification_channel]
}

resource "google_monitoring_alert_policy" "receipts_bucket_config_changed" {
  project      = var.gcp_project_id
  display_name = "MFS receipts bucket config changed"
  combiner     = "OR"

  depends_on = [time_sleep.wait_for_detection_metrics]

  conditions {
    display_name = "storage.buckets.update on the receipts bucket"

    condition_threshold {
      # gcs_bucket, not audited_resource: Cloud Storage audit entries carry the
      # bucket as their monitored resource, so pinning audited_resource here
      # would mean this alert never fires at all.
      filter          = "resource.type = \"gcs_bucket\" AND metric.type = \"logging.googleapis.com/user/${google_logging_metric.receipts_bucket_config_changed.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_COUNT"
        cross_series_reducer = "REDUCE_SUM"
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [var.notification_channel]
}
