variable "gcp_project_id" {
  description = "GCP project ID"
  type        = string
}

variable "backend_service_uri" {
  description = "Cloud Run service URL — the uptime check's target host"
  type        = string
}

variable "notification_channel" {
  description = "Full resource name of the shared alert email channel (google_monitoring_notification_channel.budget_email, declared at root — module.cost-controls also targets it)"
  type        = string
}
