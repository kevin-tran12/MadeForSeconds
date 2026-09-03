"""Tests for MCP OAuth token verification and production settings validation."""

from unittest.mock import patch

import jwt
import pytest

from app.config import Settings, validate_production_settings
from app.mcp_auth import WorkOSTokenVerifier


def _settings(**over):
    base = dict(
        environment="production",
        subscriber_jwt_secret="s" * 40,
        gcs_bucket_name="mfs-images",
        gcs_receipts_bucket_name="mfs-receipts",
        gcs_staging_bucket_name="mfs-images-staging",
        workos_authkit_domain="https://example.authkit.app",
        mcp_resource_url="https://mfs-backend.example.com/mcp",
        usage_report_audience="https://mfs-backend.example.com/api/internal/usage/weekly-report",
        alert_email="owner@example.com",
        stripe_secret_key="sk_live_" + "s" * 24,
        stripe_webhook_secret="whsec_" + "s" * 24,
    )
    base.update(over)
    return Settings(**base)


# ── validate_production_settings ──────────────────────────────────────────────

class TestValidateProductionSettings:
    def test_dev_mode_skips_all_checks(self):
        validate_production_settings(
            _settings(environment="development", workos_authkit_domain="", mcp_resource_url="")
        )

    def test_valid_production_settings_pass(self):
        validate_production_settings(_settings())

    def test_rejects_placeholder_jwt_secret(self):
        with pytest.raises(RuntimeError, match="SUBSCRIBER_JWT_SECRET"):
            validate_production_settings(
                _settings(subscriber_jwt_secret="dev-subscriber-secret-change-in-prod")
            )

    def test_rejects_short_jwt_secret(self):
        with pytest.raises(RuntimeError, match="at least 32"):
            validate_production_settings(_settings(subscriber_jwt_secret="short"))

    def test_rejects_missing_images_bucket(self):
        """Cloud Build auto-deploys the backend on every push to main while
        Terraform (which creates this bucket) is applied manually and
        separately — a revision that reaches production ahead of that apply
        must refuse to start, not silently fall back to a placeholder upload
        response later at request time."""
        with pytest.raises(RuntimeError, match="GCS_BUCKET_NAME"):
            validate_production_settings(_settings(gcs_bucket_name=""))

    def test_rejects_missing_receipts_bucket(self):
        with pytest.raises(RuntimeError, match="GCS_RECEIPTS_BUCKET_NAME"):
            validate_production_settings(_settings(gcs_receipts_bucket_name=""))

    def test_rejects_missing_staging_bucket(self):
        with pytest.raises(RuntimeError, match="GCS_STAGING_BUCKET_NAME"):
            validate_production_settings(_settings(gcs_staging_bucket_name=""))

    def test_rejects_missing_workos_domain(self):
        with pytest.raises(RuntimeError, match="WORKOS_AUTHKIT_DOMAIN"):
            validate_production_settings(_settings(workos_authkit_domain=""))

    def test_rejects_missing_resource_url(self):
        with pytest.raises(RuntimeError, match="MCP_RESOURCE_URL"):
            validate_production_settings(_settings(mcp_resource_url=""))

    def test_rejects_missing_stripe_secret_key(self):
        with pytest.raises(RuntimeError, match="STRIPE_SECRET_KEY"):
            validate_production_settings(_settings(stripe_secret_key=""))

    def test_rejects_missing_stripe_webhook_secret(self):
        with pytest.raises(RuntimeError, match="STRIPE_WEBHOOK_SECRET"):
            validate_production_settings(_settings(stripe_webhook_secret=""))


# ── workos_issuer_url normalization ───────────────────────────────────────────

class TestWorkosIssuerUrl:
    def test_full_url_unchanged(self):
        s = _settings(workos_authkit_domain="https://slug.authkit.app")
        assert s.workos_issuer_url == "https://slug.authkit.app"

    def test_bare_hostname_gets_https(self):
        s = _settings(workos_authkit_domain="slug.authkit.app")
        assert s.workos_issuer_url == "https://slug.authkit.app"

    def test_trailing_slash_stripped(self):
        s = _settings(workos_authkit_domain="https://slug.authkit.app/")
        assert s.workos_issuer_url == "https://slug.authkit.app"

    def test_jwks_url_uses_issuer(self):
        s = _settings(workos_authkit_domain="slug.authkit.app")
        assert s.workos_jwks_url == "https://slug.authkit.app/oauth2/jwks"


# ── WorkOSTokenVerifier ───────────────────────────────────────────────────────

async def _verify(
    claims=None,
    decode_exc=None,
    admins={"kevin@example.com"},
    audience="https://mfs-backend.example.com/mcp",
    enforce_audience=True,
    owner_subject="",
):
    """Run verify_token with JWKS, jwt.decode, and settings mocked."""
    verifier = WorkOSTokenVerifier()
    with (
        patch("app.mcp_auth._get_jwks_client") as mock_jwks,
        patch("app.mcp_auth.jwt.decode") as mock_decode,
        patch("app.mcp_auth.settings") as mock_settings,
    ):
        mock_settings.admin_email_set = admins
        mock_settings.workos_issuer_url = "https://example.authkit.app"
        mock_settings.mcp_audience = audience
        mock_settings.mcp_enforce_audience = enforce_audience
        mock_settings.mcp_owner_subject = owner_subject
        mock_jwks.return_value.get_signing_key_from_jwt.return_value.key = "signing-key"
        if decode_exc is not None:
            mock_decode.side_effect = decode_exc
        else:
            mock_decode.return_value = claims
        return await verifier.verify_token("some.jwt.token")


class TestWorkOSTokenVerifier:
    @pytest.mark.asyncio
    async def test_valid_admin_token_accepted(self):
        result = await _verify(
            {
                "email": "kevin@example.com",
                "sub": "user_01",
                "aud": "https://mfs-backend.example.com/mcp",
                "exp": 9999999999,
                "scope": "read write",
                "azp": "client1",
            }
        )
        assert result is not None
        assert result.token == "some.jwt.token"
        assert result.client_id == "client1"
        assert result.scopes == ["read", "write"]
        assert result.expires_at == 9999999999

    @pytest.mark.asyncio
    async def test_non_admin_email_rejected(self):
        assert await _verify({"email": "stranger@evil.com", "sub": "user_99", "exp": 9999999999}) is None

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self):
        # Any decode failure (bad signature, wrong issuer, expired) → None.
        assert await _verify(decode_exc=Exception("invalid signature")) is None

    @pytest.mark.asyncio
    async def test_missing_identity_rejected(self):
        """No email, no owner-subject match: reject outright — no fallback-allow.

        This is the P1 finding's core gap: a token with neither identity
        signal used to be accepted anyway, "relying on WorkOS sign-in
        restriction." It no longer is.
        """
        result = await _verify({"sub": "user_unknown", "exp": 9999999999, "scope": ""})
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_audience_rejected(self):
        # Simulates real PyJWT behaviour for a token signed for a different
        # resource in the same WorkOS environment.
        assert await _verify(decode_exc=jwt.InvalidAudienceError("Audience doesn't match")) is None

    @pytest.mark.asyncio
    async def test_missing_audience_claim_rejected_when_enforced(self):
        # PyJWT's actual exception for a token with no 'aud' claim at all
        # when verify_aud=True (confirmed empirically, not assumed — see the
        # PR that added this: a real RS256 token with no aud claim, decoded
        # with audience= set, raises exactly this).
        assert await _verify(decode_exc=jwt.MissingRequiredClaimError("aud")) is None

    @pytest.mark.asyncio
    async def test_audience_not_enforced_when_disabled(self):
        # The explicit escape hatch (settings.mcp_enforce_audience = False)
        # still requires a real owner identity — it only turns off the
        # audience check, not the whole verifier.
        result = await _verify(
            {"email": "kevin@example.com", "sub": "user_01", "exp": 9999999999},
            enforce_audience=False,
        )
        assert result is not None

    @pytest.mark.asyncio
    async def test_owner_subject_match_accepted_without_email(self):
        # Immutable subject match is sufficient on its own — no email claim
        # required when mcp_owner_subject is configured and matches.
        result = await _verify(
            {"sub": "user_owner", "aud": "https://mfs-backend.example.com/mcp", "exp": 9999999999},
            owner_subject="user_owner",
        )
        assert result is not None
        assert result.client_id == "workos"

    @pytest.mark.asyncio
    async def test_wrong_owner_subject_rejected(self):
        result = await _verify(
            {"sub": "user_imposter", "exp": 9999999999},
            owner_subject="user_owner",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_scope_as_list_handled(self):
        result = await _verify(
            {
                "email": "kevin@example.com",
                "sub": "user_01",
                "aud": "https://mfs-backend.example.com/mcp",
                "exp": 1,
                "scp": ["a", "b"],
            }
        )
        assert result is not None
        assert result.scopes == ["a", "b"]


# ── Sous Chef settings ────────────────────────────────────────────────────────

_REDIS = "rediss://default:t@example.upstash.io:6379"
_FEDERATION = dict(
    anthropic_federation_rule_id="fdrl_test",
    anthropic_organization_id="00000000-0000-0000-0000-000000000000",
    anthropic_service_account_id="svac_test",
)


def test_prod_rejects_a_static_anthropic_key():
    """Production authenticates with Workload Identity Federation; a static key
    would also silently shadow federation inside the SDK."""
    with pytest.raises(RuntimeError, match="Workload Identity Federation"):
        validate_production_settings(_settings(anthropic_api_key="sk-ant-test", redis_url=_REDIS))


def test_prod_rejects_federation_without_redis():
    """The monthly spend cap lives in Redis; an in-memory counter on a
    scale-to-zero instance would reset every cold start and un-cap spend."""
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        validate_production_settings(_settings(**_FEDERATION, redis_url=None))


def test_prod_rejects_partial_federation_ids():
    with pytest.raises(RuntimeError, match="set together"):
        validate_production_settings(_settings(anthropic_federation_rule_id="fdrl_test", redis_url=_REDIS))


def test_prod_accepts_federation_with_redis():
    s = _settings(**_FEDERATION, redis_url=_REDIS)
    validate_production_settings(s)
    assert s.assistant_configured is True
    assert s.assistant_federation_configured is True
    assert s.assistant_federation_partial is False


def test_dev_accepts_a_static_key():
    s = _settings(environment="development", anthropic_api_key="sk-ant-test", redis_url=None)
    validate_production_settings(s)
    assert s.assistant_configured is True and s.assistant_federation_configured is False


def test_blank_anthropic_key_means_feature_off_not_a_startup_failure():
    s = _settings()
    validate_production_settings(s)
    assert s.assistant_configured is False
