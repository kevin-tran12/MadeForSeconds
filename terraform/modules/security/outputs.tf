output "backend_sa_email" {
  description = "Backend runtime service account email"
  value       = google_service_account.backend.email
}

output "backend_sa_name" {
  description = "Backend SA's fully-qualified resource name — what google_service_account_iam_member.service_account_id expects"
  value       = google_service_account.backend.name
}

output "backend_sa_id" {
  description = "Backend SA's resource id"
  value       = google_service_account.backend.id
}

output "secret_ids" {
  description = "secret_id of each Secret Manager secret this module may create. Optional secrets are null when their source variable was blank — see local.created_secrets in secrets.tf."
  value       = local.created_secrets
}

output "backend_secret_accessor_roles" {
  description = "Distinct roles mfs-backend holds across every per-secret binding. Checked by terraform/tests/secret_pruner_iam.tftest.hcl to be exactly {roles/secretmanager.secretAccessor} — mfs-backend must never hold anything with versions.destroy on it (that permission is isolated to module.secret-maintenance's own identity, see secret_pruner.tf)."
  value       = toset([for binding in google_secret_manager_secret_iam_member.backend_secret_access : binding.role])
}

output "granted_secret_accessors" {
  description = "secret_id of every secret the backend runtime SA can read. Checked against module.backend-service.referenced_secret_ids by terraform/tests/secret_access.tftest.hcl — a secret Cloud Run injects but that is missing here fails revision creation. Read off the IAM resources themselves, not off the map that builds them, so the assertion tests what Terraform will actually create."
  value       = toset([for binding in google_secret_manager_secret_iam_member.backend_secret_access : binding.secret_id])
}

output "deploy_sa_email" {
  description = "Cloud Build deploy service account email"
  value       = google_service_account.deploy.email
}

output "deploy_sa_id" {
  description = "Deploy SA's resource id — what a Cloud Build trigger's service_account field expects"
  value       = google_service_account.deploy.id
}

output "workload_identity_provider" {
  description = "Full resource name of the GitHub Actions WIF provider — the WIF_PROVIDER value google-github-actions/auth expects. null in staging, where these resources don't exist."
  value       = try(google_iam_workload_identity_pool_provider.github[0].name, null)
}

output "terraform_sa_email" {
  description = "mfs-terraform's email — the WIF_SERVICE_ACCOUNT value google-github-actions/auth expects. null in staging."
  value       = try(google_service_account.terraform[0].email, null)
}
