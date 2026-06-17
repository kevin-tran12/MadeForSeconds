"""Tests for MCP OAuth token verification and production settings validation."""

from unittest.mock import patch

import pytest

from app.config import Settings, validate_production_settings
from app.mcp_auth import WorkOSTokenVerifier


def _settings(**over):
    base = dict(
        environment="production",
        subscriber_jwt_secret="s" * 40,
        workos_authkit_domain="https://example.authkit.app",
        mcp_resource_url="https://mfs-backend.example.com/mcp",
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

    def test_rejects_missing_workos_domain(self):
        with pytest.raises(RuntimeError, match="WORKOS_AUTHKIT_DOMAIN"):
            validate_production_settings(_settings(workos_authkit_domain=""))

    def test_rejects_missing_resource_url(self):
        with pytest.raises(RuntimeError, match="MCP_RESOURCE_URL"):
            validate_production_settings(_settings(mcp_resource_url=""))


# ── WorkOSTokenVerifier ───────────────────────────────────────────────────────

async def _verify(claims=None, decode_exc=None, admins={"kevin@example.com"}):
    """Run verify_token with JWKS, jwt.decode, and settings mocked."""
    verifier = WorkOSTokenVerifier()
    with (
        patch("app.mcp_auth._get_jwks_client") as mock_jwks,
        patch("app.mcp_auth.jwt.decode") as mock_decode,
        patch("app.mcp_auth.settings") as mock_settings,
    ):
        mock_settings.admin_email_set = admins
        mock_settings.workos_authkit_domain = "https://example.authkit.app"
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
            {"email": "kevin@example.com", "exp": 9999999999, "scope": "read write", "azp": "client1"}
        )
        assert result is not None
        assert result.token == "some.jwt.token"
        assert result.client_id == "client1"
        assert result.scopes == ["read", "write"]
        assert result.expires_at == 9999999999

    @pytest.mark.asyncio
    async def test_non_admin_email_rejected(self):
        assert await _verify({"email": "stranger@evil.com", "exp": 9999999999}) is None

    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self):
        # Any decode failure (bad signature, wrong issuer, expired) → None.
        assert await _verify(decode_exc=Exception("invalid signature")) is None

    @pytest.mark.asyncio
    async def test_missing_email_falls_back_to_workos_restriction(self):
        # No email claim: accept and rely on WorkOS sign-in restriction.
        result = await _verify({"exp": 9999999999, "scope": ""})
        assert result is not None
        assert result.client_id == "workos"
        assert result.scopes == []

    @pytest.mark.asyncio
    async def test_scope_as_list_handled(self):
        result = await _verify({"email": "kevin@example.com", "exp": 1, "scp": ["a", "b"]})
        assert result is not None
        assert result.scopes == ["a", "b"]
