# Guards Epic 2, story 2.3's core safety invariant: secretmanager.versions.
# destroy must never be reachable from mfs-backend, the public-facing runtime
# identity — that would reintroduce, for Secret Manager, exactly the
# anti-pattern 2.1/2.2 removed from Cloud Build and Cloud Storage. Destruction
# is only ever reachable through the isolated secret-pruner identity, whose
# own custom role is asserted here to be exactly list+destroy — no .enable,
# .disable, or .add, all of which the predefined secretVersionManager role
# would have carried.
#
# mock_provider means this runs at plan time against no GCP project and no
# credentials, same as tests/secret_access.tftest.hcl.

mock_provider "google" {}
mock_provider "google-beta" {}

variables {
  gcp_project_id    = "mfs-test"
  admin_emails      = "admin@example.com"
  allowed_origins   = "https://example.com"
  backend_image     = "us-central1-docker.pkg.dev/mfs-test/mfs/backend:latest"
  github_owner      = "example"
  github_repo       = "MadeForSeconds"
  state_admin_email = "admin@example.com"
  billing_account   = "000000-000000-000000"
  alert_email       = "admin@example.com"
}

run "pruner_role_is_exactly_list_and_destroy_with_all_features_enabled" {
  command = plan

  # Comparing the pruner's per-secret bindings against the custom role's own
  # id (pruner_bound_roles vs. pruner_role_id below) means comparing two
  # values both derived from google_project_iam_custom_role.secret_pruner.id,
  # which mock_provider otherwise leaves unknown at plan time — even though
  # it is, in reality, a deterministic function of the project id and role_id
  # already in config. Pinning it here makes both references resolve to the
  # same known string instead of an unresolvable pair of unknowns.
  #
  # command = apply was tried instead of this override and rejected: apply
  # plans and applies the *entire* root module, not just this one resource,
  # and mock_provider's fabricated values for unrelated resources elsewhere in
  # the config (e.g. google_service_account.name on completely unrelated SAs)
  # fail their own real-provider format validation, breaking runs that have
  # nothing to do with secret-maintenance.
  override_resource {
    target          = module.secret-maintenance[0].google_project_iam_custom_role.secret_pruner
    override_during = plan
    values = {
      id = "projects/mfs-test/roles/mfsSecretPruner"
    }
  }

  variables {
    redis_url              = "redis://placeholder.example.invalid:6379"
    stripe_secret_key      = "placeholder-stripe-key"
    stripe_webhook_secret  = "placeholder-stripe-webhook"
    stripe_product_id      = "placeholder-stripe-product"
    subscriber_jwt_secret  = "placeholder-subscriber-jwt-signing-value"
    resend_api_key         = "placeholder-resend-key"
    instagram_access_token = "placeholder-instagram-token"
    anthropic_api_key      = "placeholder-anthropic-key"
    workos_authkit_domain  = "https://example.authkit.app"
    mcp_resource_url       = "https://backend.example.invalid/mcp"
  }

  # Exact equality, not "contains" — this fails just as loudly if the role
  # ever gains .enable/.disable/.add as it would if it lost .list or .destroy.
  assert {
    condition = toset(module.secret-maintenance[0].pruner_role_permissions) == toset([
      "secretmanager.versions.destroy",
      "secretmanager.versions.list",
    ])
    error_message = "secret-pruner's custom role must be exactly versions.list + versions.destroy — got: ${join(", ", module.secret-maintenance[0].pruner_role_permissions)}"
  }

  # Every pruner binding uses the custom list+destroy role — never a broader
  # predefined one that would smuggle in .enable/.disable through a different
  # resource.
  assert {
    condition     = module.secret-maintenance[0].pruner_bound_roles == toset([module.secret-maintenance[0].pruner_role_id])
    error_message = "Every secret-pruner binding must use the custom mfsSecretPruner role, not a predefined one."
  }

  # The other side of the same invariant: mfs-backend, the public-facing
  # runtime identity, must never hold anything with versions.destroy on it —
  # that permission is isolated to secret-pruner alone (see secret_pruner.tf).
  assert {
    condition     = module.security.backend_secret_accessor_roles == toset(["roles/secretmanager.secretAccessor"])
    error_message = "mfs-backend must only ever hold roles/secretmanager.secretAccessor on any secret — found something else: ${join(", ", module.security.backend_secret_accessor_roles)}"
  }

  # secret-pruner is bound on every non-null application secret plus its own
  # canary — never on the two unrelated Cloud Build OAuth secrets, which never
  # appear in module.security.secret_ids to begin with.
  assert {
    condition = module.secret-maintenance[0].pruner_bound_secret_ids == toset([
      "admin-emails",
      "redis-url",
      "stripe-secret-key",
      "stripe-webhook-secret",
      "subscriber-jwt-secret",
      "resend-api-key",
      "instagram-access-token",
      "anthropic-api-key",
      "secret-pruner-canary",
    ])
    error_message = "secret-pruner should be bound on exactly the eight application secrets plus its own canary when every optional feature is enabled."
  }
}

run "pruner_binds_only_admin_emails_and_canary_with_no_optional_secrets" {
  command = plan

  # Same reasoning as secret_access.tftest.hcl's matching run: explicit, not
  # relied-on-by-omission, since terraform test still auto-loads an ambient
  # terraform.tfvars.
  variables {
    redis_url              = ""
    stripe_secret_key      = ""
    stripe_webhook_secret  = ""
    subscriber_jwt_secret  = ""
    resend_api_key         = ""
    instagram_access_token = ""
    anthropic_api_key      = ""
  }

  assert {
    condition = module.secret-maintenance[0].pruner_bound_secret_ids == toset([
      "admin-emails",
      "secret-pruner-canary",
    ])
    error_message = "With every optional secret blank, secret-pruner should only be bound on admin-emails and its own canary."
  }
}
