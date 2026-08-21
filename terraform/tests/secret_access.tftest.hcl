# Guards the invariant that would have blocked payments, cancellation, and
# email: every Secret Manager secret the Cloud Run template injects must also
# carry a roles/secretmanager.secretAccessor binding for the runtime service
# account. Cloud Run validates this when it creates a revision — get it wrong
# and the revision is rejected outright, so there is no degraded mode to
# discover later, only a deploy that fails.
#
# Four secrets (stripe-secret-key, stripe-webhook-secret, subscriber-jwt-secret,
# resend-api-key) were injected with no binding at all. Nothing caught it
# because the default tfvars leave all four blank, so the broken path only
# appears once someone enables the feature.
#
# mock_provider means this runs at plan time against no GCP project and no
# credentials — an ordinary CI gate rather than something only a live apply
# finds. The mocks stand in for API responses only; every value the assertions
# read (secret_id, the env list) is configured in HCL, so it is known at plan
# and is the real thing Terraform would send.

mock_provider "google" {}
mock_provider "google-beta" {}

# Required root variables that have no default. Values are arbitrary — nothing
# here is contacted.
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

# The case the review asked for: a revision with every supported optional
# feature turned on. This is the configuration that was broken.
run "every_injected_secret_is_readable_with_all_features_enabled" {
  command = plan

  # Deliberately not shaped like the real thing — no sk_/whsec_/re_ prefixes and
  # no credentials in the Redis URL. Terraform only checks these for emptiness,
  # and realistic-looking placeholders trip the gitleaks history scan in CI.
  variables {
    redis_url              = "redis://placeholder.example.invalid:6379"
    stripe_secret_key      = "placeholder-stripe-key"
    stripe_webhook_secret  = "placeholder-stripe-webhook"
    stripe_product_id      = "placeholder-stripe-product"
    subscriber_jwt_secret  = "placeholder-subscriber-jwt-signing-value"
    resend_api_key         = "placeholder-resend-key"
    instagram_access_token = "placeholder-instagram-token"
    workos_authkit_domain  = "https://example.authkit.app"
    mcp_resource_url       = "https://backend.example.invalid/mcp"
  }

  assert {
    condition     = length(output.secrets_missing_accessor) == 0
    error_message = "Cloud Run injects secrets the runtime service account cannot read: ${join(", ", output.secrets_missing_accessor)}. Every secret referenced in modules/backend-service/cloud_run.tf needs a roles/secretmanager.secretAccessor binding in modules/security/service_accounts.tf, or Cloud Run rejects the revision and the service never starts."
  }

  # The four that had no binding. Asserted by name so that deleting the
  # accessor grant — or quietly dropping one of these env vars — fails here
  # rather than passing a vacuously-empty set difference.
  assert {
    condition = length(setsubtract(
      toset(["stripe-secret-key", "stripe-webhook-secret", "subscriber-jwt-secret", "resend-api-key"]),
      output.secrets_injected_into_cloud_run
    )) == 0
    error_message = "Expected all four optional feature secrets to be injected when their tfvars are set, got: ${join(", ", output.secrets_injected_into_cloud_run)}"
  }

  assert {
    condition     = contains(output.secrets_injected_into_cloud_run, "admin-emails")
    error_message = "admin-emails is not optional — the backend cannot authorize anyone without it."
  }
}

# The default deployment: every optional secret blank. Nothing should be
# injected beyond admin-emails, and the invariant must still hold — a binding
# for a secret that was never created would fail the apply.
run "no_optional_secrets_leaves_only_admin_emails" {
  command = plan

  assert {
    condition     = length(output.secrets_missing_accessor) == 0
    error_message = "Secrets injected without a readable binding on a default deployment: ${join(", ", output.secrets_missing_accessor)}"
  }

  assert {
    condition     = output.secrets_injected_into_cloud_run == toset(["admin-emails"])
    error_message = "With every optional secret blank, admin-emails should be the only one injected, got: ${join(", ", output.secrets_injected_into_cloud_run)}"
  }
}

# Reproduces a bug mock_provider cannot reach on its own: on a live plan
# against already-applied state, google_secret_manager_secret_iam_member.
# secret_id can refresh from the real API as the fully qualified
# projects/P/secrets/NAME form even though every resource here configures it
# with the short form — observed specifically for admin-emails and redis-url,
# the two bindings that pre-date this PR and are migrated in place via
# moved.tf rather than freshly created. mock_provider always echoes back
# exactly what was configured, so by default this asymmetry never appears in
# a mocked plan; override_module injects the shape a live plan actually
# showed, so the regression stays caught without needing a real GCP project.
#
# override_module replaces every output of the targeted module for this run,
# so all five of module.security's outputs are supplied here — module.storage
# and module.backend-service both consume some of them, and an omitted one
# would plan as null rather than skip straight to a test failure.
run "already_qualified_accessor_names_still_match" {
  command = plan

  variables {
    redis_url              = "redis://placeholder.example.invalid:6379"
    stripe_secret_key      = "placeholder-stripe-key"
    stripe_webhook_secret  = "placeholder-stripe-webhook"
    stripe_product_id      = "placeholder-stripe-product"
    subscriber_jwt_secret  = "placeholder-subscriber-jwt-signing-value"
    resend_api_key         = "placeholder-resend-key"
    instagram_access_token = "placeholder-instagram-token"
    workos_authkit_domain  = "https://example.authkit.app"
    mcp_resource_url       = "https://backend.example.invalid/mcp"
  }

  override_module {
    target = module.security
    outputs = {
      backend_sa_email = "mfs-backend@mfs-test.iam.gserviceaccount.com"
      backend_sa_name  = "projects/mfs-test/serviceAccounts/mfs-backend@mfs-test.iam.gserviceaccount.com"
      backend_sa_id    = "projects/mfs-test/serviceAccounts/mfs-backend@mfs-test.iam.gserviceaccount.com"
      secret_ids = {
        admin_emails           = "admin-emails"
        redis_url              = "redis-url"
        stripe_secret_key      = "stripe-secret-key"
        stripe_webhook_secret  = "stripe-webhook-secret"
        subscriber_jwt_secret  = "subscriber-jwt-secret"
        resend_api_key         = "resend-api-key"
        instagram_access_token = "instagram-access-token"
      }
      # The form a live plan against existing state actually returned —
      # every entry fully qualified, unlike secret_ids above.
      granted_secret_accessors = toset([
        "projects/mfs-test/secrets/admin-emails",
        "projects/mfs-test/secrets/redis-url",
        "projects/mfs-test/secrets/stripe-secret-key",
        "projects/mfs-test/secrets/stripe-webhook-secret",
        "projects/mfs-test/secrets/subscriber-jwt-secret",
        "projects/mfs-test/secrets/resend-api-key",
        "projects/mfs-test/secrets/instagram-access-token",
      ])
    }
  }

  # Not vacuously true: confirm the short-form set is still non-empty and
  # complete before trusting that the (long-form vs short-form) difference
  # came out empty.
  assert {
    condition = output.secrets_injected_into_cloud_run == toset(
      ["admin-emails", "redis-url", "stripe-secret-key", "stripe-webhook-secret", "subscriber-jwt-secret", "resend-api-key"]
    )
    error_message = "Expected the usual six secrets Cloud Run injects with every feature enabled, got: ${join(", ", output.secrets_injected_into_cloud_run)}"
  }

  assert {
    condition     = length(output.secrets_missing_accessor) == 0
    error_message = "A fully qualified accessor name — the form a live plan against existing state actually returns — was wrongly treated as a different secret than its short-form counterpart: ${join(", ", output.secrets_missing_accessor)}"
  }
}
