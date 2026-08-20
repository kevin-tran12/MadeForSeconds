output "backend_sa_email" {
  description = "Backend runtime service account email"
  value       = google_service_account.backend.email
}

output "backend_sa_name" {
  description = "Backend SA's fully-qualified resource name — what google_service_account_iam_member.service_account_id expects"
  value       = google_service_account.backend.name
}

output "backend_sa_id" {
  description = "Backend SA's resource id — what a Cloud Build trigger's service_account field expects"
  value       = google_service_account.backend.id
}

output "secret_ids" {
  description = "secret_id of each Secret Manager secret this module may create. Optional secrets are null when their source variable was blank — try() turns the count-0 index-out-of-range into null rather than an error."
  value = {
    admin_emails           = google_secret_manager_secret.admin_emails.secret_id
    redis_url              = try(google_secret_manager_secret.redis_url[0].secret_id, null)
    stripe_secret_key      = try(google_secret_manager_secret.stripe_secret_key[0].secret_id, null)
    stripe_webhook_secret  = try(google_secret_manager_secret.stripe_webhook_secret[0].secret_id, null)
    subscriber_jwt_secret  = try(google_secret_manager_secret.subscriber_jwt_secret[0].secret_id, null)
    resend_api_key         = try(google_secret_manager_secret.resend_api_key[0].secret_id, null)
    instagram_access_token = try(google_secret_manager_secret.instagram_access_token[0].secret_id, null)
  }
}
