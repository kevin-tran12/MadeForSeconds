from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gcp_project_id: str = "madefor-seconds-local"
    environment: str = "development"  # "development" | "production"
    admin_emails: str = "dev@local"  # comma-separated list
    allowed_origins: str = "http://localhost:5173"  # comma-separated list
    gcs_bucket_name: str | None = None
    gcs_receipts_bucket_name: str | None = None
    gcs_staging_bucket_name: str | None = None
    # MCP OAuth (WorkOS AuthKit is the authorization server; the MCP server is a resource
    # server that only validates tokens). workos_authkit_domain is the OAuth issuer URL.
    workos_authkit_domain: str = ""  # e.g. https://<slug>.authkit.app
    mcp_resource_url: str = ""  # public URL of the MCP resource, e.g. https://<backend>/mcp
    # Audience the MCP resource server requires on every access token — a
    # token signed for a different resource in the same WorkOS environment
    # must be rejected, not merely trusted because it's WorkOS-signed. Blank
    # defaults to mcp_resource_url itself (see mcp_audience property) so this
    # never needs setting twice.
    mcp_expected_audience: str = ""
    # Fail-closed by default (P1 finding: audience was never checked at all).
    # The only legitimate reason to flip this is WorkOS AuthKit genuinely not
    # emitting an audience claim for this resource — verify that first
    # (docs/DEPLOYMENT.md § MCP token binding), don't disable pre-emptively.
    mcp_enforce_audience: bool = True
    # WorkOS 'sub' claim identifying the owner — an immutable identity check
    # independent of the email claim, which AuthKit may or may not emit.
    # Blank means identity relies on the email claim alone.
    mcp_owner_subject: str = ""
    # Comma-separated OAuth scopes every MCP access token must carry,
    # enforced by the SDK itself (AuthSettings.required_scopes in
    # mcp_server.py). Blank means no scope beyond a valid, owned token is
    # required.
    mcp_required_scopes: str = ""
    redis_url: str | None = None  # e.g. rediss://default:TOKEN@host.upstash.io:6379
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_product_id: str = ""  # Stripe Product ID for support subscription
    subscriber_jwt_secret: str = "dev-subscriber-secret-change-in-prod"
    resend_api_key: str = ""  # Resend API key for sending cancellation emails
    frontend_url: str = "http://localhost:5173"  # Frontend URL for building links in emails
    # Instagram (Meta Graph API, "Instagram API with Instagram Login" path).
    instagram_user_id: str = ""  # IG Business/Creator account numeric id
    # instagram_access_token is the dev/local token AND the initial seed for the
    # Secret Manager secret. In production the live (auto-rotated) token is read
    # from Secret Manager at runtime — see services/instagram.get_access_token.
    instagram_access_token: str = ""
    instagram_token_secret_id: str = "instagram-access-token"  # Secret Manager secret id
    instagram_refresh_invoker_email: str = ""  # SA allowed to call the refresh endpoint (OIDC)
    instagram_refresh_audience: str = ""  # Expected OIDC audience for the refresh endpoint
    usage_report_audience: str = ""  # Expected OIDC audience for the weekly usage report endpoint
    social_refresh_audience: str = ""  # Expected OIDC audience for the social token-refresh endpoint
    alert_email: str = ""  # Destination for the weekly usage report (same address as budget/uptime alerts)
    # Sous Chef assistant (Claude API). Production authenticates with Anthropic
    # Workload Identity Federation: Cloud Run's service account presents a
    # Google-signed OIDC token and the SDK exchanges it for a short-lived
    # access token under the rule below — no static key exists anywhere
    # (services/claude_auth.py). All three ids blank switches the feature off
    # — the endpoint answers 503 not_configured — rather than failing startup,
    # so staging/E2E run without it. See docs/DEPLOYMENT.md § Sous Chef.
    anthropic_federation_rule_id: str = ""  # fdrl_… — the rule matching mfs-backend's identity token
    anthropic_organization_id: str = ""  # the Anthropic organization UUID
    anthropic_service_account_id: str = ""  # svac_… — the rule's target
    anthropic_workspace_id: str = ""  # wrkspc_…; only needed when the rule spans several workspaces
    # Static key for local development and the eval script only —
    # validate_production_settings refuses it in production.
    anthropic_api_key: str = ""
    assistant_model: str = "claude-sonnet-5"
    assistant_classifier_model: str = "claude-haiku-4-5"
    assistant_monthly_cap_usd: float = 10.0  # hard stop for LLM spend, metered in Redis
    assistant_free_daily_quota: int = 5
    assistant_supporter_daily_quota: int = 50
    assistant_supporter_monthly_quota: int = 400
    # Server-side web search, offered to supporters on the sourcing spoke only.
    # $0.01 a search on top of the tokens, so it has its own monthly ceiling
    # under the spend cap; the allow-list must be a subset of any org-level
    # allow-list configured in the Claude Console.
    assistant_monthly_search_cap: int = 300
    assistant_search_domains: str = (
        "fsis.usda.gov,fda.gov,nchfp.uga.edu,seriouseats.com,thewoksoflife.com,weee.com,instacart.com"
    )
    # Appended to every Weee! search link once the affiliate programme is
    # signed up for (e.g. a network's tracking parameter); blank means plain
    # links, which is what ships today.
    weee_affiliate_query: str = ""

    @property
    def assistant_search_domain_list(self) -> list[str]:
        return [d.strip() for d in self.assistant_search_domains.split(",") if d.strip()]

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip() for e in self.admin_emails.split(",") if e.strip()}

    @property
    def assistant_federation_configured(self) -> bool:
        return bool(
            self.anthropic_federation_rule_id
            and self.anthropic_organization_id
            and self.anthropic_service_account_id
        )

    @property
    def assistant_federation_partial(self) -> bool:
        """Some but not all of the three federation ids — a misconfiguration,
        never a valid 'off'."""
        present = (
            bool(self.anthropic_federation_rule_id),
            bool(self.anthropic_organization_id),
            bool(self.anthropic_service_account_id),
        )
        return any(present) and not all(present)

    @property
    def assistant_configured(self) -> bool:
        return self.assistant_federation_configured or bool(self.anthropic_api_key)

    @property
    def instagram_configured(self) -> bool:
        """True when an Instagram account id is configured.

        The token is resolved at runtime (env var in dev, Secret Manager in
        prod), so it is not part of this check — see services/instagram.
        """
        return bool(self.instagram_user_id)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        return self.environment == "development"

    @property
    def workos_issuer_url(self) -> str:
        """Normalized WorkOS issuer URL — always has https:// scheme."""
        d = self.workos_authkit_domain.strip().rstrip("/")
        if d and not d.startswith(("https://", "http://")):
            return f"https://{d}"
        return d

    @property
    def workos_jwks_url(self) -> str:
        """JWKS endpoint for verifying WorkOS-issued access tokens."""
        return f"{self.workos_issuer_url}/oauth2/jwks"

    @property
    def mcp_audience(self) -> str:
        """The audience every MCP access token is checked against."""
        return self.mcp_expected_audience or self.mcp_resource_url

    @property
    def mcp_required_scopes_list(self) -> list[str]:
        return [s.strip() for s in self.mcp_required_scopes.split(",") if s.strip()]

    model_config = {"env_file": ".env"}


def validate_production_settings(s: "Settings") -> None:
    """Fail fast at startup when production would run with weak/missing secrets."""
    if s.is_dev:
        return
    if s.subscriber_jwt_secret == "dev-subscriber-secret-change-in-prod":
        raise RuntimeError(
            "SUBSCRIBER_JWT_SECRET must be set to a cryptographically random value in production. "
            'Generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
        )
    if len(s.subscriber_jwt_secret) < 32:
        raise RuntimeError("SUBSCRIBER_JWT_SECRET must be at least 32 characters in production")
    # Cloud Build auto-deploys the backend on every push to main; Terraform is
    # applied manually and separately. Crashing here on a missing bucket name
    # is what stops a revision deployed ahead of Terraform from silently
    # reporting fake upload success instead — see routes/admin.py and
    # mcp_server.py's request_image_upload/upload_image_from_url, which used
    # to fall back to a placeholder response whenever a bucket was unset,
    # in production as much as in dev. Crashing at import time is also the
    # SAFE failure mode: cloudbuild.yaml deploys with --no-traffic, smoke-tests
    # the tagged candidate revision, and only then promotes that exact tag. A
    # revision that crash-loops here never receives normal traffic — the
    # previous, working revision keeps serving, and no manual rollback step is
    # needed. See docs/DEPLOYMENT.md § "Terraform must be applied before
    # deploying a revision that needs it".
    if not s.gcs_bucket_name:
        raise RuntimeError(
            "GCS_BUCKET_NAME must be set in production — recipe images cannot be "
            "uploaded or attached without it. Apply Terraform before deploying a "
            "revision that depends on it."
        )
    if not s.gcs_receipts_bucket_name:
        raise RuntimeError(
            "GCS_RECEIPTS_BUCKET_NAME must be set in production — expense receipts "
            "cannot be uploaded without it. Apply Terraform before deploying a "
            "revision that depends on it."
        )
    if not s.gcs_staging_bucket_name:
        raise RuntimeError(
            "GCS_STAGING_BUCKET_NAME must be set in production — the MCP "
            "signed-PUT recipe-image flow (request_image_upload) has nowhere to "
            "land uploads without it. Apply Terraform before deploying a "
            "revision that depends on it."
        )
    if not s.workos_authkit_domain:
        raise RuntimeError(
            "WORKOS_AUTHKIT_DOMAIN must be set in production — without it the /mcp endpoint "
            "cannot validate OAuth tokens and would reject every request"
        )
    if not s.mcp_resource_url:
        raise RuntimeError(
            "MCP_RESOURCE_URL must be set in production (the public https URL of the /mcp "
            "endpoint) so OAuth resource metadata and token audiences line up"
        )
    if s.instagram_user_id and not s.instagram_refresh_invoker_email:
        raise RuntimeError(
            "INSTAGRAM_REFRESH_INVOKER_EMAIL must be set in production when Instagram is "
            "configured — it is the service account email the OIDC gate checks"
        )
    if s.instagram_user_id and not s.instagram_refresh_audience:
        raise RuntimeError(
            "INSTAGRAM_REFRESH_AUDIENCE must be set in production when Instagram is configured "
            "— without it the refresh endpoint skips OIDC audience validation"
        )
    if not s.usage_report_audience:
        raise RuntimeError(
            "USAGE_REPORT_AUDIENCE must be set in production — without it the weekly usage "
            "report endpoint always rejects Cloud Scheduler's calls"
        )
    if not s.alert_email:
        raise RuntimeError("ALERT_EMAIL must be set in production — the weekly usage report needs a destination")
    if not s.stripe_secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY must be set in production — payments cannot work without it")
    if not s.stripe_webhook_secret:
        raise RuntimeError(
            "STRIPE_WEBHOOK_SECRET must be set in production — without it /api/subscribe/webhook "
            "rejects every event with an invalid-signature error, and payments silently stop recording"
        )
    if s.anthropic_api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is set — production authenticates to Anthropic with Workload Identity "
            "Federation (Cloud Run's service account, no static key anywhere). Unset it and set "
            "ANTHROPIC_FEDERATION_RULE_ID, ANTHROPIC_ORGANIZATION_ID and ANTHROPIC_SERVICE_ACCOUNT_ID "
            "instead — docs/DEPLOYMENT.md § Sous Chef assistant."
        )
    if s.assistant_federation_partial:
        raise RuntimeError(
            "ANTHROPIC_FEDERATION_RULE_ID, ANTHROPIC_ORGANIZATION_ID and ANTHROPIC_SERVICE_ACCOUNT_ID "
            "must be set together — all three switch the Sous Chef on, all blank keeps it off; "
            "only some of them is a misconfiguration."
        )
    if s.assistant_federation_configured and not s.redis_url:
        raise RuntimeError(
            "Anthropic federation is configured but REDIS_URL is not — the Sous Chef monthly spend cap "
            "needs a counter that survives scale-to-zero (the in-memory fallback resets on every cold "
            "start, which would silently un-cap LLM spend). Set REDIS_URL or clear the ANTHROPIC_* ids."
        )


settings = Settings()
