"""Tests for MCP bearer auth (fail-closed) and production settings validation."""

from unittest.mock import patch

import pytest

from app.config import Settings, validate_production_settings
from app.mcp_server import _BearerAuthMiddleware


def _settings(**over):
    base = dict(
        environment="production",
        subscriber_jwt_secret="s" * 40,
        mcp_api_key="k" * 24,
    )
    base.update(over)
    return Settings(**base)


# ── validate_production_settings ──────────────────────────────────────────────

class TestValidateProductionSettings:
    def test_dev_mode_skips_all_checks(self):
        validate_production_settings(_settings(environment="development", mcp_api_key=""))

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

    def test_rejects_missing_mcp_api_key(self):
        with pytest.raises(RuntimeError, match="MCP_API_KEY"):
            validate_production_settings(_settings(mcp_api_key=""))

    def test_rejects_short_mcp_api_key(self):
        with pytest.raises(RuntimeError, match="MCP_API_KEY"):
            validate_production_settings(_settings(mcp_api_key="short"))


# ── _BearerAuthMiddleware ─────────────────────────────────────────────────────

def _scope(auth: bytes | None = None):
    headers = [(b"host", b"mfs-backend.example.com")]
    if auth is not None:
        headers.append((b"authorization", auth))
    return {"type": "http", "server": ("mfs-backend.example.com", 8000), "headers": headers}


async def _run_middleware(scope, api_key: str):
    inner_calls = []

    async def inner(scope, receive, send):
        inner_calls.append(scope)

    sent = []

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request"}

    middleware = _BearerAuthMiddleware(inner)
    with patch("app.mcp_server.settings") as mock_settings:
        mock_settings.mcp_api_key = api_key
        await middleware(scope, receive, send)
    return inner_calls, sent


class TestBearerAuthMiddleware:
    @pytest.mark.asyncio
    async def test_correct_token_passes_through(self):
        inner_calls, sent = await _run_middleware(_scope(b"Bearer correct-key"), "correct-key")
        assert len(inner_calls) == 1
        assert sent == []

    @pytest.mark.asyncio
    async def test_wrong_token_rejected(self):
        inner_calls, sent = await _run_middleware(_scope(b"Bearer wrong-key"), "correct-key")
        assert inner_calls == []
        assert sent[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_missing_header_rejected(self):
        inner_calls, sent = await _run_middleware(_scope(), "correct-key")
        assert inner_calls == []
        assert sent[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_empty_key_fails_closed(self):
        """An unset MCP_API_KEY must reject everything, not disable auth."""
        inner_calls, sent = await _run_middleware(_scope(b"Bearer "), "")
        assert inner_calls == []
        assert sent[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_host_header_rewritten_to_localhost(self):
        inner_calls, _ = await _run_middleware(_scope(b"Bearer correct-key"), "correct-key")
        headers = dict(inner_calls[0]["headers"])
        assert headers[b"host"] == b"localhost:8000"

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self):
        inner_calls, sent = await _run_middleware({"type": "lifespan"}, "correct-key")
        assert len(inner_calls) == 1
        assert sent == []
