# The Sous Chef assistant authenticates to the Anthropic API with Workload
# Identity Federation: Cloud Run's runtime service account presents its
# Google-signed identity token and the backend exchanges it under a federation
# rule. Terraform's whole contribution is three plain env vars naming that rule
# (backend/app/services/claude_auth.py does the rest). These runs pin the
# contract the backend relies on: the three ids arrive together or not at all
# (validate_production_settings treats a partial set as a misconfiguration, so
# it must be caught here, at plan time, not by a crash-looping revision), the
# workspace id is only sent when set (an empty string on the wire is not "use
# the rule's workspace"), and ids that are not Anthropic ids are refused.
#
# mock_provider means this runs at plan time against no GCP project and no
# credentials — every value asserted is configured in HCL and known at plan.

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

run "the_three_ids_become_plain_env_vars" {
  command = plan

  variables {
    anthropic_federation_rule_id = "fdrl_01ABCDEFabcdef0123456789XY"
    anthropic_organization_id    = "00000000-0000-0000-0000-000000000000"
    anthropic_service_account_id = "svac_01ABCDEFabcdef0123456789XY"
  }

  assert {
    condition = output.assistant_federation_env_names == toset([
      "ANTHROPIC_FEDERATION_RULE_ID",
      "ANTHROPIC_ORGANIZATION_ID",
      "ANTHROPIC_SERVICE_ACCOUNT_ID",
    ])
    error_message = "Expected exactly the three federation ids on the Cloud Run template, got: ${join(", ", output.assistant_federation_env_names)}"
  }
}

run "the_workspace_id_is_injected_only_when_set" {
  command = plan

  variables {
    anthropic_federation_rule_id = "fdrl_01ABCDEFabcdef0123456789XY"
    anthropic_organization_id    = "00000000-0000-0000-0000-000000000000"
    anthropic_service_account_id = "svac_01ABCDEFabcdef0123456789XY"
    anthropic_workspace_id       = "wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ"
  }

  assert {
    condition     = contains(output.assistant_federation_env_names, "ANTHROPIC_WORKSPACE_ID")
    error_message = "ANTHROPIC_WORKSPACE_ID must be injected when anthropic_workspace_id is set"
  }

  assert {
    condition     = length(output.assistant_federation_env_names) == 4
    error_message = "Expected the three ids plus the workspace, got: ${join(", ", output.assistant_federation_env_names)}"
  }
}

run "all_blank_injects_nothing_and_leaves_the_assistant_off" {
  command = plan

  assert {
    condition     = length(output.assistant_federation_env_names) == 0
    error_message = "With every id blank the template must carry no ANTHROPIC_* env var (the backend answers 503 not_configured), got: ${join(", ", output.assistant_federation_env_names)}"
  }
}

run "a_partial_set_of_ids_is_refused_at_plan_time" {
  command = plan

  variables {
    anthropic_federation_rule_id = "fdrl_01ABCDEFabcdef0123456789XY"
    anthropic_organization_id    = "00000000-0000-0000-0000-000000000000"
    # anthropic_service_account_id deliberately blank
  }

  expect_failures = [var.anthropic_federation_rule_id]
}

run "a_workspace_without_a_rule_is_refused" {
  command = plan

  variables {
    anthropic_workspace_id = "wrkspc_01JwQvzr7rXLA5AGx3HKfFUJ"
  }

  expect_failures = [var.anthropic_workspace_id]
}

run "ids_must_look_like_anthropic_ids" {
  command = plan

  variables {
    anthropic_federation_rule_id = "sk-ant-api03-not-a-rule-id"
    anthropic_organization_id    = "00000000-0000-0000-0000-000000000000"
    anthropic_service_account_id = "svac_01ABCDEFabcdef0123456789XY"
  }

  expect_failures = [var.anthropic_federation_rule_id]
}

run "the_organization_id_must_be_a_uuid" {
  command = plan

  variables {
    anthropic_federation_rule_id = "fdrl_01ABCDEFabcdef0123456789XY"
    anthropic_organization_id    = "my-org"
    anthropic_service_account_id = "svac_01ABCDEFabcdef0123456789XY"
  }

  expect_failures = [var.anthropic_organization_id]
}
