# The MCP server binds every WorkOS access token to this resource and this
# owner (backend/app/mcp_auth.py, #72): the token's aud must equal
# MCP_RESOURCE_URL and its sub must equal MCP_OWNER_SUBJECT (or its email an
# admin — but WorkOS access tokens carry no email claim by default). Both
# settings shipped as backend defaults and were never wired through Terraform,
# so production could not set the owner subject and every MCP token was
# rejected the moment #72 deployed. These runs pin the wiring: the two values
# reach the Cloud Run template as plain env vars, the audience switch defaults
# on, and an owner subject that is not a WorkOS user id is refused at plan.
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

run "owner_subject_and_audience_switch_reach_the_template" {
  command = plan

  variables {
    workos_authkit_domain = "https://example.authkit.app"
    mcp_resource_url      = "https://backend.example.invalid/mcp"
    mcp_owner_subject     = "user_01ABCDEFabcdef0123456789XY"
    mcp_enforce_audience  = false
  }

  assert {
    condition     = output.mcp_token_binding_env["MCP_OWNER_SUBJECT"] == "user_01ABCDEFabcdef0123456789XY"
    error_message = "MCP_OWNER_SUBJECT must reach the Cloud Run template verbatim, got: ${jsonencode(output.mcp_token_binding_env)}"
  }

  assert {
    condition     = output.mcp_token_binding_env["MCP_ENFORCE_AUDIENCE"] == "false"
    error_message = "MCP_ENFORCE_AUDIENCE must be written as the string the backend parses (\"false\"), got: ${jsonencode(output.mcp_token_binding_env)}"
  }

  assert {
    condition     = output.mcp_token_binding_env["MCP_RESOURCE_URL"] == "https://backend.example.invalid/mcp"
    error_message = "MCP_RESOURCE_URL must still be on the template alongside the binding settings, got: ${jsonencode(output.mcp_token_binding_env)}"
  }

  assert {
    condition     = length(output.mcp_token_binding_env) == 3
    error_message = "Expected exactly MCP_RESOURCE_URL, MCP_OWNER_SUBJECT and MCP_ENFORCE_AUDIENCE on the template, got: ${jsonencode(output.mcp_token_binding_env)}"
  }
}

run "defaults_keep_audience_enforcement_on" {
  command = plan

  # Explicit blanks, not relied-on-by-omission: terraform test auto-loads a
  # local terraform.tfvars the same as plan/apply does.
  variables {
    mcp_owner_subject    = ""
    mcp_enforce_audience = true
  }

  assert {
    condition     = output.mcp_token_binding_env["MCP_ENFORCE_AUDIENCE"] == "true"
    error_message = "Audience enforcement must default on — false is the documented escape hatch, not a default posture. Got: ${jsonencode(output.mcp_token_binding_env)}"
  }

  # Written even when blank, so a subject removed from tfvars is removed from
  # the next revision rather than lingering from a previous apply.
  assert {
    condition     = output.mcp_token_binding_env["MCP_OWNER_SUBJECT"] == ""
    error_message = "MCP_OWNER_SUBJECT must always be present on the template (blank when unset). Got: ${jsonencode(output.mcp_token_binding_env)}"
  }
}

run "configuring_workos_without_an_owner_subject_is_refused" {
  command = plan

  # The configuration that actually shipped after #72: issuer and resource
  # set, owner blank. It applied cleanly and rejected every MCP token.
  variables {
    workos_authkit_domain = "https://example.authkit.app"
    mcp_resource_url      = "https://backend.example.invalid/mcp"
    mcp_owner_subject     = ""
  }

  expect_failures = [var.mcp_owner_subject]
}

run "an_owner_subject_that_is_not_a_workos_user_id_is_refused" {
  command = plan

  # The obvious mistake: pasting the admin email where the immutable id goes.
  # It would deploy fine and then reject every token, since no sub equals it.
  variables {
    mcp_owner_subject = "admin@example.com"
  }

  expect_failures = [var.mcp_owner_subject]
}
