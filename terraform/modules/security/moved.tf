# ─── State address moves ──────────────────────────────────────────────────────
#
# The three hand-written secretAccessor bindings collapsed into one for_each in
# service_accounts.tf, which changes their state addresses. Without these blocks
# Terraform reads that as "destroy three bindings, create seven" — and the
# destroy of the admin-emails binding lands before its replacement, which is a
# window where the running service cannot read the secret it boots with.
#
# A moved block whose source is not in state is a no-op, so the two count-gated
# entries are safe on a deployment that never set redis_url or an Instagram token.
#
# These chain onto the root terraform/moved.tf, whose apply is still pending
# (see PR #38): that file moves each of these three from the root address into
# module.security, and this file moves them on to their for_each instance.
# Terraform follows the chain in one plan, so it does not matter whether the
# module refactor has been applied yet — the sources here are exactly the
# destinations there.
#
# Delete this file once the move has been applied and the plan is clean.

moved {
  from = google_secret_manager_secret_iam_member.backend_secret_access
  to   = google_secret_manager_secret_iam_member.backend_secret_access["admin_emails"]
}

moved {
  from = google_secret_manager_secret_iam_member.backend_redis_url_access[0]
  to   = google_secret_manager_secret_iam_member.backend_secret_access["redis_url"]
}

moved {
  from = google_secret_manager_secret_iam_member.backend_instagram_token_access[0]
  to   = google_secret_manager_secret_iam_member.backend_secret_access["instagram_access_token"]
}
