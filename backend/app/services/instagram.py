"""Instagram publishing via the Meta Graph API ("Instagram API with Instagram Login").

Publishing is a two-step container flow against ``graph.instagram.com``:
create a media container from a **public** image URL, poll it until processing
finishes, then publish it. Recipe images already live in a public GCS bucket, so
their URLs can be handed straight to Instagram.

The long-lived access token (60 days) is rotated automatically:
- in production it is read from Secret Manager at request time (short in-process
  cache) so a refreshed version is picked up without redeploying;
- ``refresh_token`` exchanges the current token for a fresh one and writes a new
  Secret Manager version — driven on a schedule by the internal refresh endpoint.

Usage errors raise ``ValueError`` (the MCP layer maps these to ``invalid_request``);
API/network failures raise ``InstagramError``. The access token is never logged.
"""

import logging
import time
import urllib.parse

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.instagram.com"
GRAPH_VERSION = "v23.0"
MAX_CAPTION_CHARS = 2200
MAX_HASHTAGS = 30

_HTTP_TIMEOUT = 15.0
_POLL_ATTEMPTS = 6
_POLL_DELAY_SECONDS = 2
_TOKEN_CACHE_TTL = 600  # 10 minutes

# In-process token cache so prod doesn't hit Secret Manager on every publish.
_token_cache: dict = {"value": "", "fetched_at": 0.0}
# Lazily-built Secret Manager client (prod only).
_sm_client = None


class InstagramError(RuntimeError):
    """An Instagram Graph API or network failure.

    ``auth=True`` marks token/permission failures so callers can prompt a
    re-auth (HTTP 401 or Graph error code 190).
    """

    def __init__(self, message: str, *, auth: bool = False):
        super().__init__(message)
        self.auth = auth


# ── Token storage (Secret Manager, prod only) ─────────────────────────────────

def _secret_client():
    global _sm_client
    if _sm_client is None:
        from google.cloud import secretmanager

        _sm_client = secretmanager.SecretManagerServiceClient()
    return _sm_client


def _read_secret(secret_id: str) -> str:
    """Read the latest version of a secret. Missing secret/version → '' (unconfigured)."""
    name = f"projects/{settings.gcp_project_id}/secrets/{secret_id}/versions/latest"
    try:
        resp = _secret_client().access_secret_version(name=name)
    except Exception as exc:  # NotFound (unconfigured) is benign; everything else is an error.
        from google.api_core import exceptions as gcp_exc

        if isinstance(exc, gcp_exc.NotFound):
            return ""
        raise InstagramError(f"Could not read Instagram token: {exc}") from exc
    return resp.payload.data.decode("utf-8").strip()


def _write_secret(secret_id: str, value: str) -> None:
    """Add a new secret version holding the refreshed token."""
    parent = f"projects/{settings.gcp_project_id}/secrets/{secret_id}"
    try:
        _secret_client().add_secret_version(
            parent=parent, payload={"data": value.encode("utf-8")}
        )
    except Exception as exc:
        raise InstagramError(f"Could not store refreshed Instagram token: {exc}") from exc


def get_access_token() -> str:
    """Return the current access token.

    Dev/local reads the env var directly; production reads Secret Manager's
    latest version with a short in-process cache. Returns '' when unconfigured.
    """
    if settings.is_dev:
        return settings.instagram_access_token
    now = time.time()
    if _token_cache["value"] and now - _token_cache["fetched_at"] < _TOKEN_CACHE_TTL:
        return _token_cache["value"]
    token = _read_secret(settings.instagram_token_secret_id)
    _token_cache["value"] = token
    _token_cache["fetched_at"] = now
    return token


def _cache_token(token: str) -> None:
    _token_cache["value"] = token
    _token_cache["fetched_at"] = time.time()


# ── Graph API plumbing ────────────────────────────────────────────────────────

def _redact(data):
    """Recursively mask any value whose key looks like a token before logging."""
    if isinstance(data, dict):
        return {k: ("***" if "token" in k.lower() else _redact(v)) for k, v in data.items()}
    if isinstance(data, list):
        return [_redact(v) for v in data]
    return data


def _graph_request(client: httpx.Client, method: str, url: str, **kwargs) -> dict:
    """Call the Graph API and return parsed JSON, raising InstagramError on failure."""
    try:
        resp = client.request(method, url, **kwargs)
    except httpx.HTTPError as exc:
        raise InstagramError(f"Instagram API request failed: {exc}") from exc

    data: dict = {}
    try:
        parsed = resp.json()
        if isinstance(parsed, dict):
            data = parsed
    except Exception:
        pass

    if resp.status_code >= 400 or "error" in data:
        err = data.get("error", {}) if isinstance(data, dict) else {}
        message = err.get("message") or f"HTTP {resp.status_code}"
        code = err.get("code")
        logger.warning(
            "Instagram API error: status=%s body=%s", resp.status_code, _redact(data)
        )
        is_auth = resp.status_code == 401 or code == 190
        raise InstagramError(
            f"Instagram {'auth ' if is_auth else ''}error: {message}", auth=is_auth
        )
    return data


def _create_container(client, user_id: str, token: str, image_url: str, caption: str) -> str:
    url = f"{GRAPH_BASE}/{GRAPH_VERSION}/{user_id}/media"
    params = {"image_url": image_url, "access_token": token}
    if caption:
        params["caption"] = caption
    data = _graph_request(client, "POST", url, params=params)
    container_id = data.get("id")
    if not container_id:
        raise InstagramError("Instagram did not return a media container id")
    return container_id


def _wait_until_finished(client, container_id: str, token: str) -> None:
    """Poll the container until it is FINISHED (Reels will rely on this too)."""
    url = f"{GRAPH_BASE}/{GRAPH_VERSION}/{container_id}"
    for attempt in range(_POLL_ATTEMPTS):
        data = _graph_request(
            client, "GET", url, params={"fields": "status_code", "access_token": token}
        )
        status = data.get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise InstagramError(f"Media processing failed (status_code={status})")
        if attempt < _POLL_ATTEMPTS - 1:
            time.sleep(_POLL_DELAY_SECONDS)
    raise InstagramError("Media did not finish processing in time; try again shortly")


def _publish_container(client, user_id: str, token: str, container_id: str) -> str:
    url = f"{GRAPH_BASE}/{GRAPH_VERSION}/{user_id}/media_publish"
    data = _graph_request(
        client, "POST", url, params={"creation_id": container_id, "access_token": token}
    )
    media_id = data.get("id")
    if not media_id:
        raise InstagramError("Instagram did not return a published media id")
    return media_id


def _fetch_permalink(client, media_id: str, token: str) -> str:
    """Best-effort permalink fetch — the post already succeeded, so swallow errors."""
    url = f"{GRAPH_BASE}/{GRAPH_VERSION}/{media_id}"
    try:
        data = _graph_request(
            client, "GET", url, params={"fields": "permalink", "access_token": token}
        )
        return data.get("permalink", "")
    except InstagramError:
        return ""


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_image_url(image_url: str) -> None:
    parsed = urllib.parse.urlparse(image_url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("image_url must be a public https URL")


def _validate_caption(caption: str) -> None:
    if caption is None:
        return
    if len(caption) > MAX_CAPTION_CHARS:
        raise ValueError(f"caption exceeds {MAX_CAPTION_CHARS} characters")
    if caption.count("#") > MAX_HASHTAGS:
        raise ValueError(f"caption has more than {MAX_HASHTAGS} hashtags")


# ── Public API ────────────────────────────────────────────────────────────────

def publish_image(image_url: str, caption: str = "") -> dict:
    """Publish a single image post to the linked Instagram account.

    Returns ``{"id", "permalink"}``. Raises ``ValueError`` for bad input /
    unconfigured state and ``InstagramError`` for API failures. The image must
    be a public https JPEG; PNG/WebP may be rejected by Instagram.
    """
    if settings.is_dev:
        logger.info("Instagram publish (dev no-op)")
        return {
            "id": "dev-ig-media",
            "permalink": "https://www.instagram.com/",
            "note": "Dev mode: not actually posted.",
        }

    user_id = settings.instagram_user_id
    token = get_access_token()
    if not user_id or not token:
        raise ValueError(
            "Instagram is not configured (set INSTAGRAM_USER_ID and the access token)"
        )
    _validate_image_url(image_url)
    _validate_caption(caption)

    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        container_id = _create_container(client, user_id, token, image_url, caption)
        _wait_until_finished(client, container_id, token)
        media_id = _publish_container(client, user_id, token, container_id)
        permalink = _fetch_permalink(client, media_id, token)

    logger.info("Instagram publish: media=%s", media_id)
    return {"id": media_id, "permalink": permalink}


def refresh_token() -> dict:
    """Exchange the current long-lived token for a fresh 60-day one.

    Writes the new token as a Secret Manager version and updates the cache.
    Returns ``{"refreshed", "expires_in_days"}`` — never the token itself.
    """
    if settings.is_dev:
        return {"refreshed": False, "note": "Dev mode: token refresh is a no-op."}

    current = get_access_token()
    if not current:
        raise InstagramError("No current Instagram token to refresh")

    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        data = _graph_request(
            client,
            "GET",
            f"{GRAPH_BASE}/refresh_access_token",
            params={"grant_type": "ig_refresh_token", "access_token": current},
        )

    new_token = data.get("access_token")
    if not new_token:
        raise InstagramError("Refresh did not return a new access token")

    _write_secret(settings.instagram_token_secret_id, new_token)
    _cache_token(new_token)

    expires_in = data.get("expires_in")
    days = round(expires_in / 86400) if expires_in else None
    logger.info("Instagram token refreshed; expires_in_days=%s", days)
    return {"refreshed": True, "expires_in_days": days}
