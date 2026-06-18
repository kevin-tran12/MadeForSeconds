from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gcp_project_id: str = "madefor-seconds-local"
    environment: str = "development"  # "development" | "production"
    admin_emails: str = "dev@local"  # comma-separated list
    allowed_origins: str = "http://localhost:5173"  # comma-separated list
    gcs_bucket_name: str | None = None
    gcs_receipts_bucket_name: str | None = None
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


settings = Settings()
