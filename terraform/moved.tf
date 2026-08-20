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
