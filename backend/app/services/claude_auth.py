"""Anthropic credentials for the Sous Chef.

Production authenticates with Anthropic **Workload Identity Federation**: Cloud
Run's runtime service account (``mfs-backend``) asks the metadata server for a
Google-signed OIDC token with audience ``https://api.anthropic.com``, and the
Anthropic SDK exchanges it (RFC 7523 ``jwt-bearer`` grant against
``POST /v1/oauth/token``) for a short-lived ``sk-ant-oat01-…`` access token
under the federation rule, refreshing before expiry. No Anthropic secret exists
anywhere — not in Secret Manager, not in GitHub, not on disk — the identity *is*
the service account, and the rule in the Anthropic Console pins its numeric
``sub`` and ``email`` claims. A static ``ANTHROPIC_API_KEY`` remains only for
local development and the eval script; ``validate_production_settings`` refuses
it in production. docs/DEPLOYMENT.md § Sous Chef assistant has the runbook.

The SDK runs the exchange synchronously inside its ``TokenCache.get_token()``,
which for ``AsyncAnthropic`` means on the event loop — on a single, scale-to-zero
instance that would stall every other request (and the health probe) for the
length of two HTTP round-trips, or the full 30 s token-endpoint timeout when
Anthropic is unwell. :class:`FederatedCredentials` memoizes the minted token so
the exchange can run in a worker thread (:meth:`FederatedCredentials.warm`)
just before each Claude call; the SDK's own cache then finds a token with more
life than its advisory refresh window and never exchanges on the loop.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable

import anyio
import httpx
from anthropic import AccessToken, WorkloadIdentityCredentials

from ..config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_BASE_URL = "https://api.anthropic.com"
# The audience requested from the metadata server and pinned by the federation
# rule's `audience` matcher — a token minted for anyone else is rejected.
GOOGLE_AUDIENCE = "https://api.anthropic.com"
METADATA_IDENTITY_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/identity"
)
METADATA_TIMEOUT_SECONDS = 5.0

# The SDK's TokenCache refreshes at expiry - 120 s (advisory) and insists at
# expiry - 30 s (mandatory). Warming ahead of the advisory window means the SDK
# never finds a token it wants to refresh itself.
REFRESH_AHEAD_SECONDS = 150
MIN_REMAINING_SECONDS = 30


def google_identity_token() -> str:
    """A fresh Google-signed OIDC token for the runtime service account.

    ``format=full`` makes Google include the ``email`` claim the federation
    rule pins alongside ``sub``; without it the exchange is denied with the
    opaque 401. Fetched anew on every exchange — never cached — so a rotated
    signing key or a restarted instance is picked up immediately.
    """
    response = httpx.get(
        METADATA_IDENTITY_URL,
        params={"audience": GOOGLE_AUDIENCE, "format": "full"},
        headers={"Metadata-Flavor": "Google"},
        timeout=METADATA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    token = response.text.strip()
    if token.count(".") != 2:
        raise RuntimeError("Google metadata server did not return an identity token (expected a JWT)")
    return token


class FederatedCredentials:
    """An Anthropic ``AccessTokenProvider`` that memoizes the federated token.

    Wraps :class:`anthropic.WorkloadIdentityCredentials` (which performs a
    fresh exchange on every call). The SDK's ``TokenCache`` calls this provider
    when it wants a token; :meth:`warm` refreshes the memo in a worker thread
    beforehand so those calls are answered from memory on the event loop.
    """

    def __init__(
        self,
        inner: Callable[..., AccessToken],
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._inner = inner
        self._clock = clock
        self._lock = threading.Lock()
        self._token: AccessToken | None = None

    def _remaining(self) -> float:
        if self._token is None:
            return 0.0
        if self._token.expires_at is None:
            return float("inf")
        return self._token.expires_at - self._clock()

    @property
    def stale(self) -> bool:
        """True when the next Claude call should be preceded by an exchange."""
        return self._remaining() < REFRESH_AHEAD_SECONDS

    def _exchange(self, *, force_refresh: bool = False) -> AccessToken:
        # Callers hold the lock. Single-flight by construction: a second thread
        # blocked on the lock re-checks the memo before exchanging again.
        self._token = self._inner(force_refresh=force_refresh)
        return self._token

    def __call__(self, *, force_refresh: bool = False) -> AccessToken:
        """The SDK's entry point. Serves the memo while it has more than the
        mandatory-refresh margin left; otherwise exchanges synchronously (rare:
        only when :meth:`warm` was skipped, or after the SDK invalidated the
        token on a 401)."""
        with self._lock:
            if not force_refresh and self._token is not None and self._remaining() > MIN_REMAINING_SECONDS:
                return self._token
            return self._exchange(force_refresh=force_refresh)

    def _refresh_if_stale(self) -> None:
        with self._lock:
            if self.stale:
                self._exchange()

    async def warm(self) -> None:
        """Run the token exchange off the event loop if the memo is stale."""
        if self.stale:
            await anyio.to_thread.run_sync(self._refresh_if_stale)

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close is not None:
            close()


def build_credentials() -> FederatedCredentials | None:
    """Credentials for the configured federation rule, or None when the three
    ids are blank (feature off, or local development on a static key)."""
    if not settings.assistant_federation_configured:
        return None
    inner = WorkloadIdentityCredentials(
        identity_token_provider=google_identity_token,
        federation_rule_id=settings.anthropic_federation_rule_id,
        organization_id=settings.anthropic_organization_id,
        service_account_id=settings.anthropic_service_account_id,
        workspace_id=settings.anthropic_workspace_id or None,
    )
    # The exchange must hit the same deployment the client talks to. The SDK
    # binds providers that implement for_base_url(); this wrapper deliberately
    # does not (a bound copy would be a different object than the one warm()
    # refreshes), so bind the inner provider here.
    inner.bind_base_url(ANTHROPIC_BASE_URL)
    return FederatedCredentials(inner)
