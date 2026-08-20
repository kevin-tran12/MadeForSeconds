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
    alert_email: str = ""  # Destination for the weekly usage report (same address as budget/uptime alerts)

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip() for e in self.admin_emails.split(",") if e.strip()}

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
    # SAFE failure mode: `gcloud run deploy` in cloudbuild.yaml has no
    # --no-traffic flag, so it waits for the new revision to pass its startup
    # probe before shifting any traffic to it. A revision that crash-loops
    # here never receives traffic — the previous, working revision keeps
    # serving, and no manual rollback step is needed. See docs/DEPLOYMENT.md
    # § "Terraform must be applied before deploying a revision that needs it".
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


settings = Settings()
