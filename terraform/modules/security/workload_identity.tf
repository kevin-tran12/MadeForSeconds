# ─── Workload Identity Federation for GitHub Actions ──────────────────────────
#
# Lets GitHub Actions authenticate as a real GCP service account with NO
# service-account key anywhere — the workflow exchanges a GitHub-issued OIDC
# token for a short-lived GCP access token, scoped by the conditions below.
# Created once, in the production project, gated on var.deployment_target
# rather than duplicated per environment: one WIF pool backs applies against
# BOTH projects (see the cross-project grants at the bottom of this file and
# staging_gcp_project_id's own description in variables.tf).
#
# Deliberately impersonates a NEW identity (mfs-terraform below), not
# mfs-deploy. mfs-deploy holds exactly three things — logWriter, actAs on
# mfs-backend, and a resource-scoped custom role limited to mfs-backend's own
# Cloud Run service (modules/backend-service/deploy_iam.tf) — the narrowest
# possible grant for "push an image, deploy it." Terraform needs to create
# IAM custom roles, service accounts, buckets, secrets, Firestore
# configuration, and monitoring policies across the whole project; pointing
# WIF at mfs-deploy would mean either broadening it back toward what Epic 2
# (stories 2.1/2.2) spent four rounds of review narrowing, or granting
# Terraform-apply-shaped permissions to the SAME identity a compromised build
# step runs as. Two identities, two blast radii, matching this repo's own
# established IAM convention (bindings live with the resource/purpose they
# grant on).

resource "google_iam_workload_identity_pool" "github" {
  count = var.deployment_target == "production" ? 1 : 0

  project                   = var.gcp_project_id
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
  description               = "Federates GitHub Actions OIDC tokens for keyless Terraform automation — see terraform/modules/security/workload_identity.tf"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  count = var.deployment_target == "production" ? 1 : 0

  project                            = var.gcp_project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Repository-scoped, not additionally ref-scoped: PR-time plan visibility
  # (a later story) needs credentials on non-main branches too, as long as
  # they're same-repo (never a fork — GitHub withholds secrets/OIDC from
  # fork-triggered pull_request workflows entirely, so this condition's real
  # job is refusing every OTHER repository, not refusing other branches).
  # Which *action* (plan vs. apply) a given workflow run is allowed to take
  # is enforced by each GitHub Actions workflow's own `on:` trigger — a push
  # to main vs. a pull_request — not duplicated into this IAM condition.
  attribute_condition = "assertion.repository == \"${var.github_owner}/${var.github_repo}\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "terraform" {
  count = var.deployment_target == "production" ? 1 : 0

  project      = var.gcp_project_id
  account_id   = "mfs-terraform"
  display_name = "MadeForSeconds Terraform (GitHub Actions, WIF)"
}

resource "google_service_account_iam_member" "terraform_workload_identity_user" {
  count = var.deployment_target == "production" ? 1 : 0

  service_account_id = google_service_account.terraform[0].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github[0].name}/attribute.repository/${var.github_owner}/${var.github_repo}"
}

# ─── mfs-terraform's own permissions — production ─────────────────────────────
#
# Broad, not a hand-enumerated custom role, unlike every other identity in
# this file: Terraform's own root config manages ~20 distinct GCP resource
# types across 6 modules (IAM bindings and custom roles, service accounts,
# GCS buckets, Secret Manager, Firestore, Cloud Run, Cloud Functions,
# Pub/Sub, Cloud Scheduler, Monitoring, Cloud Build, Artifact Registry) —
# hand-rolling a custom role covering exactly that surface, and keeping it
# in sync as the config grows, would be its own maintenance burden with a
# high cost of getting it subtly wrong (a missing permission fails an apply
# loudly and safely; the review overhead of maintaining the enumeration does
# not pay for itself the way it does for mfs-backend/mfs-deploy's much
# smaller, stable surfaces). roles/editor covers most of that CRUD surface
# but explicitly excludes IAM policy operations (confirmed the same way
# Epic 2's PR #62 confirmed it for a different identity: `gcloud iam roles
# describe roles/editor` excludes setIamPolicy) — needed here for every
# google_*_iam_member resource this config manages. Still meaningfully
# narrower than the operator's own personal credentials (Owner-equivalent)
# that this replaces for automated applies, project-scoped rather than
# organization-scoped, and reachable only via WIF from this one repository —
# no static key exists to leak.
#
# Editor's IAM-policy exclusion turned out narrower than assumed, found by
# actually running a plan under this identity (PR 8), not by more code
# review: it doesn't cover getIamPolicy/setIamPolicy on individual Pub/Sub
# topics either (google_pubsub_topic_iam_member, billing.tf) or on
# individual Secret Manager secrets in the way needed to READ a version's
# current value during Terraform's routine pre-plan refresh (distinct from
# the resourcemanager.projectIamAdmin grant below, which only covers
# project-level IAM, not resource-level IAM on things Editor doesn't already
# reach) — secretmanager.admin and pubsub.admin below close both gaps.
resource "google_project_iam_member" "terraform_editor" {
  count   = var.deployment_target == "production" ? 1 : 0
  project = var.gcp_project_id
  role    = "roles/editor"
  member  = "serviceAccount:${google_service_account.terraform[0].email}"
}

resource "google_project_iam_member" "terraform_iam_admin" {
  count   = var.deployment_target == "production" ? 1 : 0
  project = var.gcp_project_id
  role    = "roles/resourcemanager.projectIamAdmin"
  member  = "serviceAccount:${google_service_account.terraform[0].email}"
}

resource "google_project_iam_member" "terraform_service_account_admin" {
  count   = var.deployment_target == "production" ? 1 : 0
  project = var.gcp_project_id
  role    = "roles/iam.serviceAccountAdmin"
  member  = "serviceAccount:${google_service_account.terraform[0].email}"
}

resource "google_project_iam_member" "terraform_secretmanager_admin" {
  count   = var.deployment_target == "production" ? 1 : 0
  project = var.gcp_project_id
  role    = "roles/secretmanager.admin"
  member  = "serviceAccount:${google_service_account.terraform[0].email}"
}

resource "google_project_iam_member" "terraform_pubsub_admin" {
  count   = var.deployment_target == "production" ? 1 : 0
  project = var.gcp_project_id
  role    = "roles/pubsub.admin"
  member  = "serviceAccount:${google_service_account.terraform[0].email}"
}

# ─── mfs-terraform's own permissions — staging (cross-project) ────────────────
#
# The same identity, granted the same three roles on the OTHER project, so
# one WIF pool/SA pair can apply Terraform against both environments — see
# staging_gcp_project_id's description in variables.tf for why this isn't a
# second WIF pool. Skipped entirely (count = 0) until that variable is set,
# which is only true once the staging project actually exists.
resource "google_project_iam_member" "terraform_editor_staging" {
  count   = var.deployment_target == "production" && var.staging_gcp_project_id != "" ? 1 : 0
  project = var.staging_gcp_project_id
  role    = "roles/editor"
  member  = "serviceAccount:${google_service_account.terraform[0].email}"
}

resource "google_project_iam_member" "terraform_iam_admin_staging" {
  count   = var.deployment_target == "production" && var.staging_gcp_project_id != "" ? 1 : 0
  project = var.staging_gcp_project_id
  role    = "roles/resourcemanager.projectIamAdmin"
  member  = "serviceAccount:${google_service_account.terraform[0].email}"
}

resource "google_project_iam_member" "terraform_service_account_admin_staging" {
  count   = var.deployment_target == "production" && var.staging_gcp_project_id != "" ? 1 : 0
  project = var.staging_gcp_project_id
  role    = "roles/iam.serviceAccountAdmin"
  member  = "serviceAccount:${google_service_account.terraform[0].email}"
}

resource "google_project_iam_member" "terraform_secretmanager_admin_staging" {
  count   = var.deployment_target == "production" && var.staging_gcp_project_id != "" ? 1 : 0
  project = var.staging_gcp_project_id
  role    = "roles/secretmanager.admin"
  member  = "serviceAccount:${google_service_account.terraform[0].email}"
}

resource "google_project_iam_member" "terraform_pubsub_admin_staging" {
  count   = var.deployment_target == "production" && var.staging_gcp_project_id != "" ? 1 : 0
  project = var.staging_gcp_project_id
  role    = "roles/pubsub.admin"
  member  = "serviceAccount:${google_service_account.terraform[0].email}"
}
