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

moved {
  from = google_identity_platform_config.default
  to   = module.security.google_identity_platform_config.default
}

moved {
  from = google_secret_manager_secret.admin_emails
  to   = module.security.google_secret_manager_secret.admin_emails
}

moved {
  from = google_secret_manager_secret_version.admin_emails_initial
  to   = module.security.google_secret_manager_secret_version.admin_emails_initial
}

moved {
  from = google_secret_manager_secret.redis_url
  to   = module.security.google_secret_manager_secret.redis_url
}

moved {
  from = google_secret_manager_secret_version.redis_url_initial
  to   = module.security.google_secret_manager_secret_version.redis_url_initial
}

moved {
  from = google_secret_manager_secret.stripe_secret_key
  to   = module.security.google_secret_manager_secret.stripe_secret_key
}

moved {
  from = google_secret_manager_secret_version.stripe_secret_key_initial
  to   = module.security.google_secret_manager_secret_version.stripe_secret_key_initial
}

moved {
  from = google_secret_manager_secret.stripe_webhook_secret
  to   = module.security.google_secret_manager_secret.stripe_webhook_secret
}

moved {
  from = google_secret_manager_secret_version.stripe_webhook_secret_initial
  to   = module.security.google_secret_manager_secret_version.stripe_webhook_secret_initial
}

moved {
  from = google_secret_manager_secret.subscriber_jwt_secret
  to   = module.security.google_secret_manager_secret.subscriber_jwt_secret
}

moved {
  from = google_secret_manager_secret_version.subscriber_jwt_secret_initial
  to   = module.security.google_secret_manager_secret_version.subscriber_jwt_secret_initial
}

moved {
  from = google_secret_manager_secret.resend_api_key
  to   = module.security.google_secret_manager_secret.resend_api_key
}

moved {
  from = google_secret_manager_secret_version.resend_api_key_initial
  to   = module.security.google_secret_manager_secret_version.resend_api_key_initial
}

moved {
  from = google_secret_manager_secret.instagram_access_token
  to   = module.security.google_secret_manager_secret.instagram_access_token
}

moved {
  from = google_secret_manager_secret_version.instagram_access_token_initial
  to   = module.security.google_secret_manager_secret_version.instagram_access_token_initial
}

moved {
  from = google_service_account.backend
  to   = module.security.google_service_account.backend
}

moved {
  from = google_project_iam_member.backend_firestore
  to   = module.security.google_project_iam_member.backend_firestore
}

moved {
  from = google_project_iam_member.backend_logging
  to   = module.security.google_project_iam_member.backend_logging
}

moved {
  from = google_project_iam_member.backend_logging_viewer
  to   = module.security.google_project_iam_member.backend_logging_viewer
}

moved {
  from = google_secret_manager_secret_iam_member.backend_secret_access
  to   = module.security.google_secret_manager_secret_iam_member.backend_secret_access
}

moved {
  from = google_service_account_iam_member.backend_act_as_self
  to   = module.security.google_service_account_iam_member.backend_act_as_self
}

moved {
  from = google_service_account_iam_member.backend_token_creator
  to   = module.security.google_service_account_iam_member.backend_token_creator
}

moved {
  from = google_secret_manager_secret_iam_member.backend_redis_url_access
  to   = module.security.google_secret_manager_secret_iam_member.backend_redis_url_access
}

moved {
  from = google_secret_manager_secret_iam_member.backend_instagram_token_access
  to   = module.security.google_secret_manager_secret_iam_member.backend_instagram_token_access
}

moved {
  from = google_secret_manager_secret_iam_member.backend_instagram_token_adder
  to   = module.security.google_secret_manager_secret_iam_member.backend_instagram_token_adder
}

moved {
  from = google_cloud_run_v2_service.backend
  to   = module.backend-service.google_cloud_run_v2_service.backend
}

moved {
  from = google_cloud_run_v2_service_iam_member.public
  to   = module.backend-service.google_cloud_run_v2_service_iam_member.public
}

moved {
  from = google_artifact_registry_repository.backend
  to   = module.backend-service.google_artifact_registry_repository.backend
}

moved {
  from = google_project_iam_member.cloudbuild_artifact_registry
  to   = module.backend-service.google_project_iam_member.cloudbuild_artifact_registry
}

moved {
  from = google_project_iam_member.cloudbuild_run_developer
  to   = module.backend-service.google_project_iam_member.cloudbuild_run_developer
}

moved {
  from = google_cloudbuild_trigger.backend_deploy
  to   = module.backend-service.google_cloudbuild_trigger.backend_deploy
}

moved {
  from = google_service_account_iam_member.scheduler_mints_backend_oidc
  to   = module.backend-service.google_service_account_iam_member.scheduler_mints_backend_oidc
}

moved {
  from = google_cloud_scheduler_job.instagram_token_refresh
  to   = module.backend-service.google_cloud_scheduler_job.instagram_token_refresh
}

moved {
  from = google_cloud_scheduler_job.weekly_usage_report
  to   = module.backend-service.google_cloud_scheduler_job.weekly_usage_report
}

moved {
  from = google_monitoring_uptime_check_config.backend_health
  to   = module.observability.google_monitoring_uptime_check_config.backend_health
}

moved {
  from = google_monitoring_alert_policy.backend_uptime
  to   = module.observability.google_monitoring_alert_policy.backend_uptime
}

moved {
  from = google_logging_metric.backend_errors
  to   = module.observability.google_logging_metric.backend_errors
}

moved {
  from = time_sleep.wait_for_log_metrics
  to   = module.observability.time_sleep.wait_for_log_metrics
}

moved {
  from = google_monitoring_alert_policy.backend_errors
  to   = module.observability.google_monitoring_alert_policy.backend_errors
}

moved {
  from = google_logging_metric.backend_5xx
  to   = module.observability.google_logging_metric.backend_5xx
}

moved {
  from = google_monitoring_alert_policy.backend_5xx
  to   = module.observability.google_monitoring_alert_policy.backend_5xx
}

moved {
  from = google_pubsub_topic.budget_alert
  to   = module.cost-controls.google_pubsub_topic.budget_alert
}

moved {
  from = google_pubsub_topic_iam_member.budget_alert_publisher
  to   = module.cost-controls.google_pubsub_topic_iam_member.budget_alert_publisher
}

moved {
  from = data.google_billing_account.account
  to   = module.cost-controls.data.google_billing_account.account
}

moved {
  from = google_billing_budget.monthly_cap
  to   = module.cost-controls.google_billing_budget.monthly_cap
}

moved {
  from = google_service_account.budget_killer
  to   = module.cost-controls.google_service_account.budget_killer
}

moved {
  from = google_cloud_run_v2_service_iam_member.budget_killer_admin
  to   = module.cost-controls.google_cloud_run_v2_service_iam_member.budget_killer_admin
}

moved {
  from = data.archive_file.budget_killer_source
  to   = module.cost-controls.data.archive_file.budget_killer_source
}

moved {
  from = google_storage_bucket.function_source
  to   = module.cost-controls.google_storage_bucket.function_source
}

moved {
  from = google_storage_bucket_object.budget_killer_source
  to   = module.cost-controls.google_storage_bucket_object.budget_killer_source
}

moved {
  from = google_cloudfunctions2_function.budget_killer
  to   = module.cost-controls.google_cloudfunctions2_function.budget_killer
}

moved {
  from = google_cloud_run_v2_service_iam_member.budget_killer_invoker
  to   = module.cost-controls.google_cloud_run_v2_service_iam_member.budget_killer_invoker
}

moved {
  from = google_project_iam_member.budget_killer_eventarc
  to   = module.cost-controls.google_project_iam_member.budget_killer_eventarc
}

moved {
  from = google_service_account_iam_member.pubsub_token_creator
  to   = module.cost-controls.google_service_account_iam_member.pubsub_token_creator
}

moved {
  from = google_cloudfunctions2_function.budget_resetter
  to   = module.cost-controls.google_cloudfunctions2_function.budget_resetter
}

moved {
  from = google_cloud_run_v2_service_iam_member.budget_resetter_invoker
  to   = module.cost-controls.google_cloud_run_v2_service_iam_member.budget_resetter_invoker
}

moved {
  from = google_service_account_iam_member.scheduler_mints_budget_killer_oidc
  to   = module.cost-controls.google_service_account_iam_member.scheduler_mints_budget_killer_oidc
}

moved {
  from = google_monitoring_alert_policy.budget_breaker_tripped
  to   = module.cost-controls.google_monitoring_alert_policy.budget_breaker_tripped
}

moved {
  from = google_cloud_scheduler_job.budget_breaker_reset
  to   = module.cost-controls.google_cloud_scheduler_job.budget_breaker_reset
}

# ─── Second wave: staging conditional-resource gating (Epic 8, PR 5) ─────────
#
# Adding `count` to already-applied resources/modules shifts their state
# address (e.g. `module.storage.google_firestore_backup_schedule.daily` ->
# `...daily[0]`). Terraform's automatic index-compatibility only covered some
# of these for free (confirmed empirically per resource, not assumed) — a
# whole-module `count` addition never gets it, and even two structurally
# identical sibling resources (the daily and weekly backup schedules) split:
# weekly moved for free, daily didn't. Explicit `moved` blocks for all of
# them, rather than relying on which ones happened to be free, so this stays
# correct if Terraform's heuristic ever changes.
#
# module.secret-maintenance has no entry here: every one of its resources was
# still pending its first-ever apply (from PR #63) when this ran, so there
# was no existing address to move *from* — it's simply created at the
# indexed address `module.secret-maintenance[0].*` directly.

moved {
  from = module.cost-controls
  to   = module.cost-controls[0]
}

moved {
  from = module.storage.google_firestore_backup_schedule.daily
  to   = module.storage.google_firestore_backup_schedule.daily[0]
}

moved {
  from = module.storage.google_firestore_backup_schedule.weekly
  to   = module.storage.google_firestore_backup_schedule.weekly[0]
}

moved {
  from = module.backend-service.google_cloud_scheduler_job.weekly_usage_report
  to   = module.backend-service.google_cloud_scheduler_job.weekly_usage_report[0]
}

moved {
  from = google_storage_bucket.tf_state
  to   = google_storage_bucket.tf_state[0]
}

moved {
  from = google_storage_bucket_iam_member.tf_state_admin
  to   = google_storage_bucket_iam_member.tf_state_admin[0]
}

# Found and gated while actually bootstrapping staging (not anticipated when
# the rest of this second wave was written) — see the comment on the
# resource itself in modules/backend-service/cloudbuild.tf.
moved {
  from = module.backend-service.google_cloudbuild_trigger.backend_deploy
  to   = module.backend-service.google_cloudbuild_trigger.backend_deploy[0]
}
