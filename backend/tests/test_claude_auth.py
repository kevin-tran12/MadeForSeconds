"""Workload Identity Federation plumbing for the Sous Chef's Claude client."""

from unittest.mock import patch

import httpx
import pytest
from anthropic import AccessToken, WorkloadIdentityCredentials

from app.config import settings
from app.services import claude_auth

FEDERATION = {
    "anthropic_federation_rule_id": "fdrl_test",
    "anthropic_organization_id": "00000000-0000-0000-0000-000000000000",
    "anthropic_service_account_id": "svac_test",
}


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


class Inner:
    """Stands in for WorkloadIdentityCredentials: every call is a fresh exchange."""

    def __init__(self, clock, lifetime=600):
        self.clock = clock
        self.lifetime = lifetime
        self.calls = []
        self.closed = False

    def __call__(self, *, force_refresh=False):
        self.calls.append(force_refresh)
        return AccessToken(token=f"sk-ant-oat01-{len(self.calls)}", expires_at=int(self.clock() + self.lifetime))

    def close(self):
        self.closed = True


# ── identity token from the metadata server ───────────────────────────────────

def test_identity_token_requests_full_format_for_the_configured_audience():
    response = httpx.Response(200, text="aaa.bbb.ccc\n", request=httpx.Request("GET", claude_auth.METADATA_IDENTITY_URL))
    with patch("app.services.claude_auth.httpx.get", return_value=response) as get:
        assert claude_auth.google_identity_token() == "aaa.bbb.ccc"
    kwargs = get.call_args.kwargs
    assert get.call_args.args[0] == claude_auth.METADATA_IDENTITY_URL
    assert kwargs["params"] == {"audience": "https://api.anthropic.com", "format": "full"}
    assert kwargs["headers"] == {"Metadata-Flavor": "Google"}
    assert kwargs["timeout"] == claude_auth.METADATA_TIMEOUT_SECONDS


def test_identity_token_rejects_non_jwt_and_http_errors():
    request = httpx.Request("GET", claude_auth.METADATA_IDENTITY_URL)
    with patch("app.services.claude_auth.httpx.get", return_value=httpx.Response(200, text="not a jwt", request=request)):
        with pytest.raises(RuntimeError, match="identity token"):
            claude_auth.google_identity_token()
    with patch("app.services.claude_auth.httpx.get", return_value=httpx.Response(404, text="", request=request)):
        with pytest.raises(httpx.HTTPStatusError):
            claude_auth.google_identity_token()


# ── memoizing provider ────────────────────────────────────────────────────────

def test_provider_exchanges_once_and_serves_the_memo():
    clock = Clock()
    inner = Inner(clock)
    creds = claude_auth.FederatedCredentials(inner, clock=clock)
    assert creds.stale is True
    first = creds()
    assert first.token == "sk-ant-oat01-1" and inner.calls == [False]
    assert creds().token == "sk-ant-oat01-1" and len(inner.calls) == 1
    assert creds.stale is False


def test_provider_exchanges_again_near_expiry_or_when_forced():
    clock = Clock()
    inner = Inner(clock, lifetime=600)
    creds = claude_auth.FederatedCredentials(inner, clock=clock)
    creds()
    clock.now += 600 - claude_auth.REFRESH_AHEAD_SECONDS + 1  # inside the warm window, outside the hard one
    assert creds.stale is True
    assert creds().token == "sk-ant-oat01-1", "still served: more than the mandatory margin remains"
    clock.now += claude_auth.REFRESH_AHEAD_SECONDS - claude_auth.MIN_REMAINING_SECONDS
    assert creds().token == "sk-ant-oat01-2", "inside the mandatory margin: exchanged synchronously"
    assert creds(force_refresh=True).token == "sk-ant-oat01-3"
    assert inner.calls[-1] is True


@pytest.mark.asyncio
async def test_warm_exchanges_in_a_worker_thread_only_when_stale():
    clock = Clock()
    inner = Inner(clock)
    creds = claude_auth.FederatedCredentials(inner, clock=clock)
    with patch("app.services.claude_auth.anyio.to_thread.run_sync", wraps=claude_auth.anyio.to_thread.run_sync) as run_sync:
        await creds.warm()
        assert run_sync.call_count == 1 and len(inner.calls) == 1
        await creds.warm()
        assert run_sync.call_count == 1, "fresh memo: no thread hop at all"
        clock.now += 600 - claude_auth.REFRESH_AHEAD_SECONDS + 1
        await creds.warm()
        assert run_sync.call_count == 2 and len(inner.calls) == 2
    assert creds().token == "sk-ant-oat01-2"


def test_provider_close_closes_inner():
    inner = Inner(Clock())
    claude_auth.FederatedCredentials(inner).close()
    assert inner.closed is True


# ── build_credentials ─────────────────────────────────────────────────────────

def test_build_credentials_is_none_without_the_three_ids(monkeypatch):
    for name in FEDERATION:
        monkeypatch.setattr(settings, name, "")
    assert claude_auth.build_credentials() is None
    monkeypatch.setattr(settings, "anthropic_federation_rule_id", "fdrl_only")
    assert settings.assistant_federation_partial is True
    assert claude_auth.build_credentials() is None


def test_build_credentials_wraps_workload_identity_bound_to_the_api(monkeypatch):
    for name, value in FEDERATION.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "anthropic_workspace_id", "")
    creds = claude_auth.build_credentials()
    assert isinstance(creds, claude_auth.FederatedCredentials)
    inner = creds._inner
    assert isinstance(inner, WorkloadIdentityCredentials)
    assert inner._identity_token_provider is claude_auth.google_identity_token
    assert inner._federation_rule_id == "fdrl_test"
    assert inner._organization_id == FEDERATION["anthropic_organization_id"]
    assert inner._service_account_id == "svac_test"
    assert inner._workspace_id is None, "blank workspace must not go on the wire as an empty string"
    assert inner._base_url == "https://api.anthropic.com"
    creds.close()


def test_build_credentials_passes_workspace_when_set(monkeypatch):
    for name, value in FEDERATION.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "anthropic_workspace_id", "wrkspc_test")
    creds = claude_auth.build_credentials()
    assert creds._inner._workspace_id == "wrkspc_test"
    creds.close()


def test_wrapper_is_not_rebound_by_the_sdk_client(monkeypatch):
    """The SDK binds providers exposing for_base_url() by copying them; a copy
    would be a different object than the one warm() refreshes. The wrapper
    therefore must not expose it, and the SDK must accept it as-is."""
    import anthropic

    for name, value in FEDERATION.items():
        monkeypatch.setattr(settings, name, value)
    creds = claude_auth.build_credentials()
    assert not hasattr(creds, "for_base_url")
    client = anthropic.AsyncAnthropic(credentials=creds)
    assert client.credentials is creds
    assert client.api_key is None
    creds.close()
    del client


def test_sdk_token_cache_serves_the_warmed_memo_without_exchanging():
    """End-to-end through the SDK's own TokenCache: once warm() has run, the
    cache's get_token() never triggers a second exchange."""
    from anthropic import TokenCache

    clock = Clock()
    inner = Inner(clock)
    creds = claude_auth.FederatedCredentials(inner, clock=clock)
    creds()  # what warm() does, minus the thread
    cache = TokenCache(creds)
    assert cache.get_token() == "sk-ant-oat01-1"
    assert cache.get_token() == "sk-ant-oat01-1"
    assert len(inner.calls) == 1
