output "canary_secret_id" {
  description = "secret_id of the disposable canary secret used to validate the pruning/recovery drill (see docs/DEPLOYMENT.md § Secret version pruning) without touching a real application secret"
  value       = google_secret_manager_secret.canary.secret_id
}

output "pruner_sa_email" {
  description = "secret-pruner service account email — the operator impersonates this to run the recovery drill's dry-run checks manually"
  value       = google_service_account.secret_pruner.email
}

output "pruner_role_permissions" {
  description = "Permissions on the mfsSecretPruner custom role. Checked by terraform/tests/secret_pruner_iam.tftest.hcl to be exactly versions.list + versions.destroy — this is the module boundary that keeps .enable/.disable off it."
  value       = google_project_iam_custom_role.secret_pruner.permissions
}

output "pruner_role_id" {
  description = "Full resource id of the mfsSecretPruner custom role — compared against pruner_bound_roles below to confirm every binding actually uses it"
  value       = google_project_iam_custom_role.secret_pruner.id
}

output "pruner_bound_secret_ids" {
  description = "secret_id of every secret secret-pruner holds its custom role on"
  value       = toset([for binding in google_secret_manager_secret_iam_member.pruner_access : binding.secret_id])
}

output "pruner_bound_roles" {
  description = "Distinct roles used across every secret-pruner binding — should always be exactly {pruner_role_id}, never a predefined role smuggled in some other way"
  value       = toset([for binding in google_secret_manager_secret_iam_member.pruner_access : binding.role])
}
