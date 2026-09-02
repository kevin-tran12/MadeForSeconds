variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "gcp_region" {
  description = "Region for the pruner Cloud Function"
  type        = string
}

# Same shape as modules/backend-service's own secret_ids input — one map, kept
# in sync with module.security's local.created_secrets so a secret added there
# is picked up here too without a second list to maintain. Optional secrets are
# null when their source variable was blank; those are filtered out below.
variable "secret_ids" {
  description = "secret_id of each Secret Manager secret, keyed the same as module.security's output. Optional ones may be null."
  type = object({
    admin_emails           = string
    redis_url              = string
    stripe_secret_key      = string
    stripe_webhook_secret  = string
    subscriber_jwt_secret  = string
    resend_api_key         = string
    instagram_access_token = string
    anthropic_api_key      = string
  })
}

# Empty by default — a secret is only ever destroyed if it is both listed here
# and dry-run is off for it (see secret_pruner_function/main.py). Populate this
# only after the recovery drill against the canary secret has succeeded; see
# docs/DEPLOYMENT.md § Secret version pruning.
variable "write_enabled_secret_ids" {
  description = "secret_id values the pruner is allowed to actually destroy versions on. Every secret not listed here runs in dry-run (log-only) mode regardless of what the pruning algorithm would otherwise select."
  type        = list(string)
  default     = []
}

variable "notification_channel" {
  description = "Full resource name of the shared alert email channel (google_monitoring_notification_channel.budget_email, declared at root)"
  type        = string
}

variable "scheduler_agent_email" {
  description = "Cloud Scheduler's service agent email (google_project_service_identity.cloudscheduler, declared at root — shared with module.backend-service and module.cost-controls, which need the same agent for their own scheduler jobs)"
  type        = string
}

variable "state_admin_email" {
  description = "Google account of whoever runs terraform apply — granted roles/iam.serviceAccountTokenCreator on secret_pruner so backend/scripts/smoke_test_secret_pruner.py can impersonate the real pruner identity, the same way service_accounts.tf's backend_operator_impersonation lets smoke_test_receipt_role.py impersonate mfs-backend"
  type        = string
}
