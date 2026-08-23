variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "gcp_region" {
  description = "Region for the kill/reset Cloud Functions"
  type        = string
}

variable "billing_account" {
  description = "GCP billing account ID"
  type        = string
}

variable "monthly_budget_amount" {
  description = "Monthly budget cap in USD"
  type        = number
}

variable "project_number" {
  description = "GCP project NUMBER (data.google_project.project.number, declared once at root in apis.tf) — needed for the budget filter and the Pub/Sub service agent's generated email, neither of which accepts the project id"
  type        = string
}

variable "backend_service_name" {
  description = "Cloud Run service name — the breaker acts directly on this service's IAM policy"
  type        = string
}

variable "notification_channel" {
  description = "Full resource name of the shared alert email channel (google_monitoring_notification_channel.budget_email, declared at root — module.observability also targets it)"
  type        = string
}

variable "scheduler_agent_email" {
  description = "Cloud Scheduler's service agent email (google_project_service_identity.cloudscheduler, declared at root — module.backend-service needs the same agent for a different grant)"
  type        = string
}

variable "images_bucket_name" {
  description = "module.storage.images_bucket_name. The breaker publishes/clears status.json here on trip/reset — reused rather than a dedicated bucket, since it already grants allUsers get on every object it holds. The accessor IAM grant lives in this module (billing.tf), not beside the bucket in modules/storage/buckets.tf like the backend's own grant: this module already depends on module.storage for the bucket name, so a grant declared the other way round — module.storage taking this module's SA email as an input — would be a module dependency cycle."
  type        = string
}
